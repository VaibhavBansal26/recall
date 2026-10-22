import asyncio
import base64
import contextlib
import logging
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket
from pydantic import BaseModel, ValidationError

from app.agent.deps import AgentDeps
from app.agent.graph import stream_capture
from app.agent.nodes.capture import ack_stream
from app.agent.state import AgentState
from app.auth import COOKIE_NAME
from app.config import get_settings
from app.db.models import Speaker, Utterance
from app.services import sessions as svc
from app.tracks import Endpointing
from app.voice.barge_in import BargeInDetector
from app.voice.events import (
    AssistantDeltaEvent,
    AssistantDoneEvent,
    AudioEvent,
    DiagramEvent,
    EndSpeechEvent,
    ErrorEvent,
    InterruptedEvent,
    InterruptEvent,
    LatencyEvent,
    LinksEvent,
    NotesEvent,
    SessionEvent,
    SpeechStartEvent,
    StartEvent,
    TextEvent,
    TranscriptEvent,
    UtteranceEvent,
    client_event_adapter,
)
from app.voice.latency import TurnLatency
from app.voice.provider import SttEvent, SttSession, VoiceProvider
from app.voice.speech import SentenceChunker, clean_for_speech

router = APIRouter()
log = logging.getLogger(__name__)

WINDOW_SIZE = 6  # earlier user utterances passed to capture as context


class _Outbox:
    """Serialises sends: the receive loop and the reply task both write to the socket."""

    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws
        self._lock = asyncio.Lock()

    async def send(self, event: BaseModel) -> None:
        async with self._lock:
            await self._ws.send_text(event.model_dump_json())


class _Connection:
    def __init__(
        self, out: _Outbox, deps: AgentDeps, graph: Any, voice: VoiceProvider | None
    ) -> None:
        self.out = out
        self.deps = deps
        self.graph = graph
        self.voice = voice
        self.detector = BargeInDetector()
        self.session_id: uuid.UUID | None = None
        self.track: str = deps.settings.default_track
        self.stt: SttSession | None = None
        self.window: list[str] = []
        self.reply_task: asyncio.Task[None] | None = None
        self.capture_tasks: set[asyncio.Task[None]] = set()
        self.capture_lock = asyncio.Lock()
        self._partial: Utterance | None = None

    # ---- lifecycle ----

    async def start(self, event: StartEvent) -> None:
        if self.voice is None:
            await self.out.send(ErrorEvent(message="Voice provider is not configured"))
            return
        await self.close_stt()
        await self.interrupt(announce=False)
        async with self.deps.sessionmaker() as db:
            if event.session_id is not None:
                session = await svc.get_session(db, event.session_id)
                if session is None:
                    await self.out.send(ErrorEvent(message="Session not found"))
                    return
            else:
                track = await svc.get_track(db, event.track)
                if track is None:
                    await self.out.send(ErrorEvent(message=f"Unknown track {event.track!r}"))
                    return
                session = await svc.create_session(db, track)
            self.session_id, self.track = session.id, session.track.slug
            endpointing = Endpointing.model_validate(session.track.config.get("endpointing", {}))
        self.window = []
        if self.voice.audio_input:
            try:
                # Capture mode: wait longer before deciding the user has finished a thought.
                self.stt = await self.voice.open_stt(
                    silence_ms=endpointing.capture_silence_ms, on_event=self.on_stt_event
                )
            except Exception:
                log.exception("could not open STT")
                await self.out.send(ErrorEvent(message="Speech recognition is unavailable"))
        await self.out.send(
            SessionEvent(
                session_id=self.session_id,
                track=self.track,
                audio_input=self.stt is not None,
            )
        )

    async def close(self) -> None:
        await self.close_stt()
        await self.interrupt(announce=False)
        await asyncio.gather(*self.capture_tasks, return_exceptions=True)

    async def close_stt(self) -> None:
        if self.stt is not None:
            with contextlib.suppress(Exception):
                await self.stt.close()
            self.stt = None

    # ---- inbound ----

    async def audio(self, pcm: bytes) -> None:
        if self.stt is not None:
            with contextlib.suppress(Exception):
                await self.stt.send_audio(pcm)

    async def speech_start(self) -> None:
        if self.detector.should_interrupt(assistant_speaking=self._speaking, speech_started=True):
            await self.interrupt(announce=True)

    async def end_speech(self) -> None:
        if self.stt is not None:
            with contextlib.suppress(Exception):
                await self.stt.finalize()

    async def on_stt_event(self, event: SttEvent) -> None:
        if not event.final:
            await self.out.send(TranscriptEvent(text=event.text))
            if self.detector.should_interrupt(
                assistant_speaking=self._speaking, partial_text=event.text
            ):
                await self.interrupt(announce=True)
            return
        await self.user_turn(event.text, confidence=event.confidence)

    async def user_turn(self, text: str, confidence: float | None = None) -> None:
        if self.session_id is None:
            await self.out.send(ErrorEvent(message="Send a start event first"))
            return
        latency = TurnLatency()
        # A new user turn while the assistant is talking is a barge-in.
        await self.interrupt(announce=True)
        async with self.deps.sessionmaker() as db:
            stored = await svc.add_utterance(db, self.session_id, Speaker.user, text, confidence)
        await self.out.send(UtteranceEvent(id=stored.id, speaker=Speaker.user, text=stored.text))

        state = AgentState(
            session_id=self.session_id,
            track=self.track,
            user_text=text,
            transcript_window=self.window[-WINDOW_SIZE:],
        )
        self.window.append(text)
        self.reply_task = asyncio.create_task(self._reply(state, latency))
        capture = asyncio.create_task(self._capture(state))
        self.capture_tasks.add(capture)
        capture.add_done_callback(self.capture_tasks.discard)

    # ---- barge-in ----

    @property
    def _speaking(self) -> bool:
        return self.reply_task is not None and not self.reply_task.done()

    async def interrupt(self, *, announce: bool) -> None:
        task = self.reply_task
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        partial, self._partial = self._partial, None
        if announce:
            await self.out.send(InterruptedEvent())
            if partial is not None:
                await self.out.send(
                    UtteranceEvent(
                        id=partial.id,
                        speaker=Speaker.assistant,
                        text=partial.text,
                        interrupted=True,
                    )
                )

    # ---- turns ----

    async def _reply(self, state: AgentState, latency: TurnLatency) -> None:
        assert self.voice is not None and self.session_id is not None
        spoken: list[str] = []
        chunker = SentenceChunker()

        async def speak(sentence: str) -> None:
            assert self.voice is not None
            text = clean_for_speech(sentence)
            if not text:
                return
            spoken.append(text)
            await self.out.send(AssistantDeltaEvent(text=text))
            async for chunk in self.voice.synthesize(text):
                latency.mark_first_audio()
                await self.out.send(AudioEvent(data=base64.b64encode(chunk).decode()))

        try:
            async for token in ack_stream(self.deps, state):
                latency.mark_first_token()
                for sentence in chunker.feed(token):
                    await speak(sentence)
            if (tail := chunker.flush()) is not None:
                await speak(tail)
            async with self.deps.sessionmaker() as db:
                stored = await svc.add_utterance(
                    db, self.session_id, Speaker.assistant, " ".join(spoken)
                )
            await self.out.send(
                UtteranceEvent(id=stored.id, speaker=Speaker.assistant, text=stored.text)
            )
            await self.out.send(AssistantDoneEvent())
            log.info(
                "turn latency stt->token=%sms token->audio=%sms stt->audio=%sms",
                latency.stt_to_first_token_ms(),
                latency.first_token_to_audio_ms(),
                latency.stt_to_first_audio_ms(),
            )
            await self.out.send(
                LatencyEvent(
                    stt_to_first_token_ms=latency.stt_to_first_token_ms(),
                    first_token_to_audio_ms=latency.first_token_to_audio_ms(),
                    stt_to_first_audio_ms=latency.stt_to_first_audio_ms(),
                )
            )
        except asyncio.CancelledError:
            # Keep what was actually said, marked as interrupted.
            if spoken:
                self._partial = await asyncio.shield(self._store_partial(" ".join(spoken)))
            raise
        except Exception:
            log.exception("reply failed")
            with contextlib.suppress(Exception):
                await self.out.send(ErrorEvent(message="Reply failed"))

    async def _store_partial(self, text: str) -> Utterance:
        assert self.session_id is not None
        async with self.deps.sessionmaker() as db:
            utterance = Utterance(
                session_id=self.session_id, speaker=Speaker.assistant, text=text, interrupted=True
            )
            db.add(utterance)
            await db.commit()
            return utterance

    async def _capture(self, state: AgentState) -> None:
        # Serialised so two quick turns cannot both create the same note.
        async with self.capture_lock:
            try:
                async for node, update in stream_capture(self.graph, state):
                    if node == "capture" and update.captured:
                        await self.out.send(NotesEvent(items=update.captured))
                    elif node == "enrich":
                        if update.diagrams:
                            await self.out.send(DiagramEvent(items=update.diagrams))
                        if update.links:
                            await self.out.send(LinksEvent(items=update.links))
            except Exception:
                log.exception("capture failed")
                with contextlib.suppress(Exception):
                    await self.out.send(ErrorEvent(message="Note capture failed"))


@router.websocket("/ws/voice")
async def voice_ws(ws: WebSocket) -> None:
    state = ws.app.state
    settings = get_settings()
    if state.auth.enabled:
        # Cookies ride along on cross-site WebSocket handshakes, so check Origin as well.
        origin = ws.headers.get("origin")
        if origin is not None and origin not in settings.cors_origins:
            await ws.close(code=4403)
            return
        if not state.auth.verify(ws.cookies.get(COOKIE_NAME)):
            await ws.close(code=4401)
            return
    await ws.accept()
    conn = _Connection(_Outbox(ws), state.deps, state.graph, state.voice)
    if state.voice_error:
        await conn.out.send(ErrorEvent(message=state.voice_error))
    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                await conn.audio(message["bytes"])
                continue
            try:
                event = client_event_adapter.validate_json(message.get("text") or "")
            except ValidationError:
                await conn.out.send(ErrorEvent(message="Invalid event"))
                continue
            if isinstance(event, StartEvent):
                await conn.start(event)
            elif isinstance(event, TextEvent):
                await conn.user_turn(event.text)
            elif isinstance(event, InterruptEvent):
                await conn.interrupt(announce=True)
            elif isinstance(event, SpeechStartEvent):
                await conn.speech_start()
            elif isinstance(event, EndSpeechEvent):
                await conn.end_speech()
    finally:
        await conn.close()

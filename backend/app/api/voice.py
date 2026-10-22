import asyncio
import base64
import contextlib
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, WebSocket
from pydantic import BaseModel, ValidationError
from sqlalchemy import select, update

from app.agent.confusion import ConfusionTracker
from app.agent.deps import AgentDeps
from app.agent.graph import stream_capture
from app.agent.nodes import explain as explain_node
from app.agent.nodes import read_back as read_back_node
from app.agent.nodes.capture import ack_stream
from app.agent.nodes.chitchat import chitchat_stream
from app.agent.nodes.recall_quiz import QuizSession, QuizStep
from app.agent.nodes.teach_back import TeachBackSession, suggest_topic
from app.agent.router import Mode, Route, route_turn
from app.agent.state import AgentState, DiagramItem
from app.auth import COOKIE_NAME
from app.config import get_settings
from app.db.models import (
    BriefStatus,
    CaptureEvent,
    LearningSession,
    Source,
    SourceStatus,
    Speaker,
    Utterance,
)
from app.services import briefs as briefs_svc
from app.services import confusion as confusion_svc
from app.services import diagrams as diagram_svc
from app.services import ingest as ingest_svc
from app.services import notes as notes_svc
from app.services import retrieval
from app.services import sessions as svc
from app.tracks import Endpointing
from app.voice.barge_in import BargeInDetector
from app.voice.events import (
    AssistantDeltaEvent,
    AssistantDoneEvent,
    AudioEvent,
    ConfusionEvent,
    DiagramEvent,
    EndSpeechEvent,
    ErrorEvent,
    ExplainEvent,
    InterruptedEvent,
    InterruptEvent,
    LatencyEvent,
    LinksEvent,
    ModeEvent,
    NotesEvent,
    QuizActionEvent,
    QuizStartEvent,
    SessionEvent,
    SpeechStartEvent,
    StartEvent,
    TeachBackDoneEvent,
    TeachBackEvent,
    TeachBackStartEvent,
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

AfterSpeech = Callable[[], Awaitable[None]]


class _Outbox:
    """Serialises sends: the receive loop and the reply task both write to the socket."""

    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws
        self._lock = asyncio.Lock()

    async def send(self, event: BaseModel) -> None:
        async with self._lock:
            await self._ws.send_text(event.model_dump_json())


async def _once(text: str) -> AsyncIterator[str]:
    yield text


class _Connection:
    def __init__(
        self, out: _Outbox, deps: AgentDeps, graph: Any, voice: VoiceProvider | None
    ) -> None:
        self.out = out
        self.deps = deps
        self.graph = graph
        self.voice = voice
        self.detector = BargeInDetector()
        self.confusion = ConfusionTracker()
        self.session_id: uuid.UUID | None = None
        self.track: str = deps.settings.default_track
        self.stt: SttSession | None = None
        self.window: list[str] = []
        self.reply_task: asyncio.Task[None] | None = None
        self.capture_tasks: set[asyncio.Task[None]] = set()
        self.capture_lock = asyncio.Lock()
        self._partial: Utterance | None = None
        # conversation mode and per-mode state
        self.mode: Mode = Mode.capture
        self.quiz: QuizSession | None = None
        self.readback: read_back_node.ReadBackSession | None = None
        self.ingest_source_id: uuid.UUID | None = None
        self.teachback: TeachBackSession | None = None
        self.speed: float = 1.0
        self.active_note_id: uuid.UUID | None = None  # last note we explained/read/quizzed
        self.last_topic: str | None = None
        self._silence_task: asyncio.Task[None] | None = None
        self._bg: set[asyncio.Task[Any]] = set()

    # ---- lifecycle ----

    async def start(self, event: StartEvent) -> None:
        if self.voice is None:
            await self.out.send(ErrorEvent(message="Voice provider is not configured"))
            return
        await self.close_stt()
        await self.interrupt(announce=False)
        self._cancel_silence()
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
        self.confusion = ConfusionTracker()
        self.mode, self.quiz, self.readback, self.speed = Mode.capture, None, None, 1.0
        self.active_note_id = self.last_topic = None
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
        self._cancel_silence()
        await self.close_stt()
        await self.interrupt(announce=False)
        await asyncio.gather(*self.capture_tasks, *self._bg, return_exceptions=True)

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
        await self.user_turn(event.text, confidence=event.confidence, words=event.words)

    # ---- the turn: route to a mode ----

    async def user_turn(
        self,
        text: str,
        confidence: float | None = None,
        words: list[dict[str, Any]] | None = None,
    ) -> None:
        if self.session_id is None:
            await self.out.send(ErrorEvent(message="Send a start event first"))
            return
        latency = TurnLatency()
        self._cancel_silence()
        # A new user turn while the assistant is talking is a barge-in.
        await self.interrupt(announce=True)
        async with self.deps.sessionmaker() as db:
            stored = await svc.add_utterance(
                db, self.session_id, Speaker.user, text, confidence, words
            )
        await self.out.send(UtteranceEvent(id=stored.id, speaker=Speaker.user, text=stored.text))

        state = AgentState(
            session_id=self.session_id,
            track=self.track,
            user_text=text,
            transcript_window=self.window[-WINDOW_SIZE:],
        )
        previous = self.window[-1] if self.window else None
        self.window.append(text)

        trigger = self.confusion.check(text)
        route = await route_turn(self.deps.llm, text, self.mode, self.session_id)

        if self.mode == Mode.recall_quiz and trigger and trigger.startswith("phrase"):
            # In a quiz, "I don't get it" climbs the hint ladder instead of leaving the quiz.
            await self._record_confusion(trigger)
            route = Route(Mode.recall_quiz, command="hint")
        elif trigger and route.mode in (Mode.capture, Mode.explain, Mode.chitchat):
            await self._confusion_turn(trigger, previous or text, latency)
            return

        await self._dispatch(route, state, latency, words)

    async def _dispatch(
        self,
        route: Route,
        state: AgentState,
        latency: TurnLatency,
        words: list[dict[str, Any]] | None = None,
    ) -> None:
        if route.mode == Mode.teach_back:
            await self._handle_teach_back(route, state, latency, words)
        elif route.mode == Mode.recall_quiz:
            await self._handle_quiz(route, latency)
        elif route.mode == Mode.read_back:
            await self._handle_read_back(route, latency)
        elif route.mode == Mode.ingest_review:
            await self._handle_ingest_review(route, latency)
        elif route.mode == Mode.explain:
            await self._handle_explain(route.topic or state.user_text, latency, simple=False)
        elif route.mode == Mode.chitchat:
            await self._set_mode(Mode.capture)
            self._start_reply(
                chitchat_stream(self.deps, state.session_id, state.user_text), latency
            )
        else:  # capture
            if self.mode != Mode.capture:
                await self._set_mode(Mode.capture)
            self._start_reply(ack_stream(self.deps, state), latency)
            capture = asyncio.create_task(self._capture(state))
            self.capture_tasks.add(capture)
            capture.add_done_callback(self.capture_tasks.discard)

    async def _set_mode(self, mode: Mode) -> None:
        if mode == self.mode:
            return
        self.mode = mode
        if mode != Mode.recall_quiz:
            self.quiz = None
        if mode != Mode.read_back:
            self.readback = None
            self.speed = 1.0
        if mode != Mode.teach_back:
            self.teachback = None
        await self._persist_mode(mode)

    async def _persist_mode(self, mode: Mode) -> None:
        if self.session_id is not None:
            async with self.deps.sessionmaker() as db:
                await db.execute(
                    update(LearningSession)
                    .where(LearningSession.id == self.session_id)
                    .values(mode=mode.value)
                )
                await db.commit()
        await self.out.send(ModeEvent(mode=mode.value))

    # ---- explain, with the "I don't get it" simplification ----

    async def _handle_explain(
        self, topic: str, latency: TurnLatency, *, simple: bool, trigger: str | None = None
    ) -> None:
        assert self.session_id is not None
        await self._set_mode(Mode.capture)
        session_id = self.session_id
        note = await explain_node.find_related_note(self.deps, self.track, topic)
        if note is not None:
            self.active_note_id = note.id
        self.last_topic = topic

        # The diagram is drawn alongside the spoken explanation, never words alone.
        diagram_task = asyncio.create_task(
            explain_node.explain_diagram(
                self.deps, session_id=session_id, topic=topic, note=note, track=self.track
            )
        )
        self._bg.add(diagram_task)
        diagram_task.add_done_callback(self._bg.discard)

        spoken: list[str] = []

        async def tokens() -> AsyncIterator[str]:
            async for token in explain_node.explain_stream(
                self.deps,
                session_id=session_id,
                topic=topic,
                simple=simple,
                note=note,
                track=self.track,
            ):
                spoken.append(token)
                yield token

        async def after() -> None:
            diagram: DiagramItem | None = None
            try:
                kind, source = await diagram_task
                diagram = DiagramItem(
                    note_id=note.id if note else session_id, kind=kind.value, source=source
                )
            except Exception:
                log.exception("explain diagram failed")
            await self.out.send(
                ExplainEvent(
                    explain_id=uuid.uuid4(),
                    topic=topic,
                    simple=simple,
                    text="".join(spoken).strip(),
                    diagram=diagram,
                    note_id=note.id if note else None,
                )
            )
            if not simple:
                self._arm_silence_watch()

        self._start_reply(tokens(), latency, after=after)

    async def _record_confusion(self, trigger: str) -> None:
        assert self.session_id is not None
        async with self.deps.sessionmaker() as db:
            await confusion_svc.log_confusion(
                db, session_id=self.session_id, note_id=self.active_note_id, trigger=trigger
            )
        await self.out.send(ConfusionEvent(trigger=trigger, note_id=self.active_note_id))

    async def _confusion_turn(
        self, trigger: str, fallback_topic: str, latency: TurnLatency
    ) -> None:
        """Log it, mark the note fragile, and explain again in simplified form (rule 4)."""
        await self._record_confusion(trigger)
        topic = self.last_topic
        if topic is None and self.active_note_id is not None:
            async with self.deps.sessionmaker() as db:
                note = await notes_svc.get_note(db, self.active_note_id)
            topic = note.title if note else None
        await self._handle_explain(topic or fallback_topic, latency, simple=True, trigger=trigger)

    def _arm_silence_watch(self) -> None:
        wait = get_settings().confusion_silence_s
        if wait <= 0:
            return
        self._cancel_silence()
        self._silence_task = asyncio.create_task(self._silence_watch(wait))

    def _cancel_silence(self) -> None:
        if self._silence_task is not None and not self._silence_task.done():
            self._silence_task.cancel()
        self._silence_task = None

    async def _silence_watch(self, wait: float) -> None:
        """A long silence after an explanation is a sign it did not land."""
        await asyncio.sleep(wait)
        if self.session_id is None or self._speaking:
            return
        try:
            await self._confusion_turn(
                "silence after explanation", self.last_topic or "that", TurnLatency()
            )
        except Exception:
            log.exception("silence follow-up failed")

    # ---- recall_quiz ----

    async def start_brief(self, brief_id: uuid.UUID | None = None) -> None:
        """The spoken daily brief: the weakest notes, one question each, then what is due."""
        if self.session_id is None:
            await self.out.send(ErrorEvent(message="Send a start event first"))
            return
        await self.interrupt(announce=True)
        self._cancel_silence()
        latency = TurnLatency()
        settings = self.deps.settings
        tz = ZoneInfo(settings.user_timezone)
        async with self.deps.sessionmaker() as db:
            brief = await briefs_svc.get_brief(db, brief_id) if brief_id else None
            if brief is None:  # asked by voice before the morning cron ran: build it now
                brief, _ = await briefs_svc.create_brief(
                    db,
                    track_slug=self.track,
                    now=datetime.now(UTC),
                    tz=tz,
                    questions=settings.brief_questions,
                )
            if brief.status == BriefStatus.completed:
                self._start_reply(_once("You've already done today's brief."), latency)
                return
            items = await briefs_svc.brief_items(db, brief)
            if not items:
                self._start_reply(
                    _once("There's nothing to put in a brief yet. Capture some ideas first."),
                    latency,
                )
                return
            due_today = await briefs_svc.due_today_count(
                db, track_slug=self.track, now=datetime.now(UTC), tz=tz
            )
            await briefs_svc.mark_started(db, brief, self.session_id)
            brief_pk = brief.id
        self.quiz = QuizSession(
            self.deps,
            self.session_id,
            self.track,
            outro=briefs_svc.spoken_outro(due_today),
            brief_id=brief_pk,
        )
        self.mode = Mode.recall_quiz
        await self._persist_mode(self.mode)
        step = await self.quiz.start(items=items, lead=briefs_svc.spoken_intro(len(items)))
        await self._play_quiz_step(step, latency)

    async def start_quiz(
        self, *, note_id: uuid.UUID | None = None, topic: str | None = None
    ) -> None:
        if self.session_id is None:
            await self.out.send(ErrorEvent(message="Send a start event first"))
            return
        await self.interrupt(announce=True)
        self._cancel_silence()
        latency = TurnLatency()
        note_ids: list[uuid.UUID] | None = None
        if topic:
            async with self.deps.sessionmaker() as db:
                found = await retrieval.hybrid_search(
                    db, self.deps.embedder, track_slug=self.track, query=topic, limit=6
                )
            if not found:
                self._start_reply(_once(f"I couldn't find any notes about {topic}."), latency)
                return
            note_ids = [n.id for n in found]
        self.quiz = QuizSession(self.deps, self.session_id, self.track)
        self.mode = Mode.recall_quiz
        await self._persist_mode(self.mode)
        step = await self.quiz.start(note_id=note_id, note_ids=note_ids)
        await self._play_quiz_step(step, latency)

    async def _handle_quiz(self, route: Route, latency: TurnLatency) -> None:
        if self.quiz is None:  # a "quiz me" or "start my brief" request from speech
            if route.command == "brief":
                await self.start_brief()
            else:
                await self.start_quiz(topic=route.topic)
            return
        command = route.command or "answer"
        text = self.window[-1] if self.window else ""
        if command == "hint" or command == "forgot":
            step = await self.quiz.hint()
        elif command == "skip":
            step = await self.quiz.skip()
        elif command == "end":
            step = await self.quiz.end()
        else:
            step = await self.quiz.answer(text)
        await self._play_quiz_step(step, latency)

    async def quiz_action(self, action: str) -> None:
        if self.quiz is None or self.session_id is None:
            return
        await self.interrupt(announce=True)
        latency = TurnLatency()
        step = {
            "hint": self.quiz.hint,
            "forgot": self.quiz.hint,
            "skip": self.quiz.skip,
            "end": self.quiz.end,
        }[action]
        await self._play_quiz_step(await step(), latency)

    async def _play_quiz_step(self, step: QuizStep, latency: TurnLatency) -> None:
        for event in step.events:
            await self.out.send(event)
            if event.note_id is not None:
                self.active_note_id = event.note_id
        if step.diagram_note_id is not None:
            self._spawn(self._send_note_diagram(step.diagram_note_id))
        if step.ended:
            if self.quiz is not None and self.quiz.brief_id is not None:
                async with self.deps.sessionmaker() as db:
                    brief = await briefs_svc.get_brief(db, self.quiz.brief_id)
                    if brief is not None:
                        await briefs_svc.mark_completed(db, brief)
            await self._set_mode(Mode.capture)
        self._start_reply(_once(step.spoken), latency)

    # ---- read_back ----

    async def _handle_read_back(self, route: Route, latency: TurnLatency) -> None:
        assert self.session_id is not None
        session_id = self.session_id
        rb = self.readback
        command = route.command or "start"

        if rb is None or command == "start":
            rb = await read_back_node.start(self.deps, self.track, route.topic)
            if rb is None:
                about = f" about {route.topic}" if route.topic else ""
                self._start_reply(_once(f"I don't have any notes{about} yet."), latency)
                return
            self.readback = rb
            await self._set_mode(Mode.read_back)
            self.readback = rb  # _set_mode clears it when leaving read_back
            self.speed = rb.speed
            step = await read_back_node.read_current(self.deps, rb, session_id)
        elif command in ("next", "skip"):
            step = await read_back_node.advance(self.deps, rb, session_id)
        elif command in ("slower", "faster"):
            read_back_node.change_speed(rb, command)
            self.speed = rb.speed
            step = await read_back_node.read_current(self.deps, rb, session_id)
        elif command == "repeat":
            step = await read_back_node.read_current(self.deps, rb, session_id)
        else:  # stop
            step = read_back_node.stop(rb)

        spoken = step.spoken
        for event in step.events:
            await self.out.send(event)
        if step.note_id is not None:
            self.active_note_id = step.note_id
            self._spawn(self._send_note_diagram(step.note_id))

        if step.finished:
            if step.question_item is not None:
                # Finish by asking one question: hand over to the quiz for that item.
                self.quiz = QuizSession(self.deps, session_id, self.track)
                self.mode = Mode.recall_quiz
                quiz_step = await self.quiz.start(items=[step.question_item])
                for quiz_event in quiz_step.events:
                    await self.out.send(quiz_event)
                spoken = f"{spoken} {quiz_step.spoken}"
                await self._persist_mode(self.mode)
                self.readback = None
                self.speed = 1.0
            else:
                await self._set_mode(Mode.capture)
        self._start_reply(_once(spoken), latency)

    # ---- teach_back: the learner explains out loud; we listen, then score it ----

    async def start_teachback(self, topic: str | None, latency: TurnLatency | None = None) -> None:
        if self.session_id is None:
            await self.out.send(ErrorEvent(message="Send a start event first"))
            return
        await self.interrupt(announce=True)
        self._cancel_silence()
        topic = (topic or "").strip() or suggest_topic(self.track)
        self.teachback = TeachBackSession(self.deps, self.session_id, self.track, topic)
        self.mode = Mode.teach_back
        await self._persist_mode(self.mode)
        await self.out.send(self.teachback.listening())
        self._start_reply(
            _once(
                f"Okay. Explain {topic} in your own words, as if to a friend. "
                "Take your time, and say I'm done when you've finished."
            ),
            latency or TurnLatency(),
        )

    async def _handle_teach_back(
        self,
        route: Route,
        state: AgentState,
        latency: TurnLatency,
        words: list[dict[str, Any]] | None,
    ) -> None:
        command = route.command or "segment"
        if command == "start" or self.teachback is None:
            await self.start_teachback(route.topic, latency)
            return
        if command == "segment":  # part of the explanation: listen, never interrupt
            await self.out.send(self.teachback.add(state.user_text, words))
            return
        await self.finish_teachback(cancel=command == "cancel", latency=latency)

    async def finish_teachback(self, *, cancel: bool, latency: TurnLatency | None = None) -> None:
        tb = self.teachback
        if tb is None:
            return
        latency = latency or TurnLatency()
        await self.interrupt(announce=True)
        if cancel:
            await self.out.send(TeachBackEvent(phase="cancelled", topic=tb.topic))
            await self._set_mode(Mode.capture)
            self._start_reply(_once("Okay, no problem. We'll skip the scoring."), latency)
            return
        await self.out.send(TeachBackEvent(phase="scoring", topic=tb.topic, words=tb.word_count))
        related = await explain_node.find_related_note(self.deps, self.track, tb.topic)
        event, feedback, _row = await tb.finish(note_id=related.id if related else None)
        await self.out.send(event)
        if feedback is None:
            spoken = (
                "That was a bit short to score. Try again with a few more sentences about "
                f"{tb.topic}."
            )
        else:
            spoken = feedback.spoken()
        await self._set_mode(Mode.capture)
        self._start_reply(_once(spoken), latency)

    # ---- ingest_review: what was filed from new material, and do you want to keep it ----

    async def _handle_ingest_review(self, route: Route, latency: TurnLatency) -> None:
        command = route.command or "start"
        async with self.deps.sessionmaker() as db:
            if command == "start" or self.ingest_source_id is None:
                source = (
                    await db.execute(
                        select(Source)
                        .where(Source.status == SourceStatus.ready)
                        .order_by(Source.updated_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if source is None:
                    await self._set_mode(Mode.capture)
                    self._start_reply(_once("Nothing new is waiting for your review."), latency)
                    return
                self.ingest_source_id = source.id
                spoken = await self._ingest_summary(db, source)
                await self._set_mode(Mode.ingest_review)
                self.ingest_source_id = source.id  # _set_mode only clears state it owns
                self._start_reply(_once(spoken), latency)
                return

            source = (
                await db.execute(select(Source).where(Source.id == self.ingest_source_id))
            ).scalar_one_or_none()
            if source is None or source.status != SourceStatus.ready:
                spoken = "That one has already been handled."
                done = True
            elif command == "approve":
                count = await ingest_svc.approve(db, source)
                spoken = f"Done. I confirmed {count} note{'s' if count != 1 else ''}."
                done = True
            elif command == "undo":
                events = (
                    await db.execute(
                        select(CaptureEvent.id).where(
                            CaptureEvent.source_id == source.id, CaptureEvent.undone.is_(False)
                        )
                    )
                ).scalars()
                for event_id in list(events):
                    await notes_svc.undo_capture(db, event_id)
                await ingest_svc.approve(db, source)  # nothing left to confirm; closes it
                spoken = "Okay, I removed everything that source added."
                done = True
            elif command == "end":
                spoken = "Okay, they will wait for you on the sources page."
                done = True
            else:  # repeat
                spoken = await self._ingest_summary(db, source)
                done = False
        if done:
            self.ingest_source_id = None
            await self._set_mode(Mode.capture)
        self._start_reply(_once(spoken), latency)

    async def _ingest_summary(self, db: Any, source: Source) -> str:
        summary = await ingest_svc.summarize(db, source)
        headline = summary.headline(source.track.name if source.track else None)
        titles = (
            await db.execute(
                select(CaptureEvent)
                .where(CaptureEvent.source_id == source.id, CaptureEvent.undone.is_(False))
                .limit(3)
            )
        ).scalars()
        names = [e.note.title for e in titles if e.note is not None]
        about = f" from {source.title}" if source.title else ""
        sample = f" For example: {'; '.join(names)}." if names else ""
        return f"{headline[:-1]}{about}.{sample} Shall I keep them?"

    # ---- diagrams for notes ----

    async def _send_note_diagram(self, note_id: uuid.UUID) -> None:
        """Show the note's diagram, drawing one first if it has none yet."""
        async with self.deps.sessionmaker() as db:
            diagram = await diagram_svc.get_diagram(db, note_id)
            if diagram is None:
                note = await notes_svc.get_note(db, note_id)
                if note is None:
                    return
                kind, source = await diagram_svc.build_note_diagram(
                    self.deps.llm, note, session_id=self.session_id
                )
                diagram = await diagram_svc.save_diagram(db, note_id, kind, source)
            item = DiagramItem(note_id=note_id, kind=diagram.kind.value, source=diagram.source)
        await self.out.send(DiagramEvent(items=[item]))

    def _spawn(self, coro: Awaitable[Any]) -> None:
        async def run() -> None:
            try:
                await coro
            except Exception:
                log.exception("background task failed")

        task = asyncio.create_task(run())
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

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

    # ---- speaking ----

    def _start_reply(
        self,
        tokens: AsyncIterator[str],
        latency: TurnLatency,
        after: AfterSpeech | None = None,
    ) -> None:
        self.reply_task = asyncio.create_task(self._reply(tokens, latency, after))

    async def _reply(
        self,
        tokens: AsyncIterator[str],
        latency: TurnLatency,
        after: AfterSpeech | None,
    ) -> None:
        assert self.voice is not None and self.session_id is not None
        spoken: list[str] = []
        chunker = SentenceChunker()
        speed = self.speed if self.speed != 1.0 else None

        async def speak(sentence: str) -> None:
            assert self.voice is not None
            text = clean_for_speech(sentence)
            if not text:
                return
            spoken.append(text)
            await self.out.send(AssistantDeltaEvent(text=text))
            async for chunk in self.voice.synthesize(text, speed):
                latency.mark_first_audio()
                await self.out.send(AudioEvent(data=base64.b64encode(chunk).decode()))

        try:
            async for token in tokens:
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
            if after is not None:
                await after()
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
                async for node, update_state in stream_capture(self.graph, state):
                    if node == "capture" and update_state.captured:
                        self.active_note_id = update_state.captured[0].note_id
                        await self.out.send(NotesEvent(items=update_state.captured))
                    elif node == "enrich":
                        if update_state.diagrams:
                            await self.out.send(DiagramEvent(items=update_state.diagrams))
                        if update_state.links:
                            await self.out.send(LinksEvent(items=update_state.links))
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
            elif isinstance(event, QuizStartEvent):
                if event.brief_id is not None:
                    await conn.start_brief(event.brief_id)
                else:
                    await conn.start_quiz(note_id=event.note_id)
            elif isinstance(event, QuizActionEvent):
                await conn.quiz_action(event.action)
            elif isinstance(event, TeachBackStartEvent):
                await conn.start_teachback(event.topic)
            elif isinstance(event, TeachBackDoneEvent):
                await conn.finish_teachback(cancel=event.cancel)
    finally:
        await conn.close()

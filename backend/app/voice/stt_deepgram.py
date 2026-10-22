"""Deepgram live streaming STT (https://developers.deepgram.com/docs/live-streaming-audio)."""

import asyncio
import contextlib
import json
import logging
from typing import Any
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection, connect

from app.config import Settings
from app.voice.provider import SttCallback, SttEvent, SttSession

log = logging.getLogger(__name__)
KEEPALIVE_S = 5


class TranscriptAssembler:
    """Turns Deepgram `Results` / `UtteranceEnd` messages into partial and final transcripts.

    Deepgram emits many `is_final` fragments per utterance; the utterance is complete at
    `speech_final` (endpointing), `UtteranceEnd`, or after a `Finalize` request.
    """

    def __init__(self) -> None:
        self._finals: list[str] = []
        self._words: list[dict[str, float | str]] = []
        self._confidence: float | None = None

    def feed(self, msg: dict[str, Any]) -> list[SttEvent]:
        kind = msg.get("type")
        if kind == "UtteranceEnd":
            return self.flush()
        if kind != "Results":
            return []
        alt = msg["channel"]["alternatives"][0]
        text = str(alt.get("transcript", "")).strip()
        if msg.get("is_final"):
            if text:
                self._finals.append(text)
                self._confidence = alt.get("confidence")
                self._words.extend(
                    {
                        "w": str(w.get("punctuated_word") or w.get("word", "")),
                        "start": float(w["start"]),
                        "end": float(w["end"]),
                    }
                    for w in alt.get("words", [])
                    if "start" in w and "end" in w
                )
            if msg.get("speech_final") or msg.get("from_finalize"):
                return self.flush()
            return [SttEvent(" ".join(self._finals), False)] if self._finals else []
        if text:
            return [SttEvent(" ".join([*self._finals, text]), False)]
        return []

    def flush(self) -> list[SttEvent]:
        if not self._finals:
            return []
        event = SttEvent(" ".join(self._finals), True, self._confidence, self._words or None)
        self._finals, self._words, self._confidence = [], [], None
        return [event]


class DeepgramStt(SttSession):
    def __init__(self, ws: ClientConnection, on_event: SttCallback) -> None:
        self._ws = ws
        self._on_event = on_event
        self._assembler = TranscriptAssembler()
        self._tasks = [
            asyncio.create_task(self._receive_loop()),
            asyncio.create_task(self._keepalive_loop()),
        ]

    @classmethod
    async def connect(
        cls, settings: Settings, *, silence_ms: int, on_event: SttCallback
    ) -> "DeepgramStt":
        params = {
            "model": settings.stt_model,
            "encoding": "linear16",
            "sample_rate": 16000,
            "channels": 1,
            "interim_results": "true",
            "punctuate": "true",
            "smart_format": "true",
            "endpointing": silence_ms,
            "utterance_end_ms": max(1000, silence_ms),
        }
        ws = await connect(
            f"wss://api.deepgram.com/v1/listen?{urlencode(params)}",
            additional_headers={"Authorization": f"Token {settings.deepgram_api_key}"},
        )
        return cls(ws, on_event)

    async def send_audio(self, pcm: bytes) -> None:
        await self._ws.send(pcm)

    async def finalize(self) -> None:
        await self._ws.send(json.dumps({"type": "Finalize"}))

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self._ws.send(json.dumps({"type": "CloseStream"}))
            await self._ws.close()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _receive_loop(self) -> None:
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                for event in self._assembler.feed(json.loads(raw)):
                    await self._on_event(event)
        except Exception:
            log.exception("deepgram receive loop ended")

    async def _keepalive_loop(self) -> None:
        # Deepgram closes idle sockets after ~10 s; push-to-talk leaves long gaps.
        with contextlib.suppress(Exception):
            while True:
                await asyncio.sleep(KEEPALIVE_S)
                await self._ws.send(json.dumps({"type": "KeepAlive"}))

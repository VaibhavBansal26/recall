"""ElevenLabs Scribe v2 realtime STT (https://elevenlabs.io/docs/api-reference/speech-to-text/v-1-speech-to-text-realtime)."""

import asyncio
import base64
import contextlib
import json
import logging
from typing import Any
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection, connect

from app.config import Settings
from app.voice.provider import SttCallback, SttEvent, SttSession

log = logging.getLogger(__name__)
SAMPLE_RATE = 16000
KEEPALIVE_S = 5
# 100 ms of silence: used to flush on push-to-talk release and to keep an idle socket open.
SILENCE = b"\x00" * (SAMPLE_RATE // 10 * 2)
ERRORS = {
    "error",
    "auth_error",
    "quota_exceeded",
    "commit_throttled",
    "unaccepted_terms",
    "rate_limited",
    "queue_overflow",
    "resource_exhausted",
    "session_time_limit_exceeded",
    "input_error",
    "invalid_request",
    "chunk_size_exceeded",
    "transcriber_error",
}


def events_from_message(msg: dict[str, Any]) -> list[SttEvent]:
    """Turn one Scribe message into transcript events.

    We ask for timestamps, so a segment is final on `committed_transcript_with_timestamps`
    (the plain `committed_transcript` that may precede it is ignored to avoid a duplicate).
    """
    kind = msg.get("message_type")
    text = str(msg.get("text", "")).strip()
    if kind == "partial_transcript":
        return [SttEvent(text, False)] if text else []
    if kind == "committed_transcript_with_timestamps":
        if not text:
            return []
        words: list[dict[str, float | str]] = [
            {"w": str(w.get("text", "")), "start": float(w["start"]), "end": float(w["end"])}
            for w in msg.get("words") or []
            if w.get("type", "word") == "word" and "start" in w and "end" in w
        ]
        return [SttEvent(text, True, None, words or None)]
    return []


class ElevenLabsStt(SttSession):
    def __init__(self, ws: ClientConnection, on_event: SttCallback) -> None:
        self._ws = ws
        self._on_event = on_event
        self._last_send = asyncio.get_running_loop().time()
        self._tasks = [
            asyncio.create_task(self._receive_loop()),
            asyncio.create_task(self._keepalive_loop()),
        ]

    @classmethod
    async def connect(
        cls, settings: Settings, *, silence_ms: int, on_event: SttCallback
    ) -> "ElevenLabsStt":
        params = {
            "model_id": settings.elevenlabs_stt_model,
            "audio_format": "pcm_16000",
            "commit_strategy": "vad",
            "vad_silence_threshold_secs": max(0.3, silence_ms / 1000),
            "include_timestamps": "true",
            "language_code": settings.stt_language,
        }
        ws = await connect(
            f"wss://api.elevenlabs.io/v1/speech-to-text/realtime?{urlencode(params)}",
            additional_headers={"xi-api-key": settings.elevenlabs_api_key},
        )
        return cls(ws, on_event)

    async def _send_chunk(self, pcm: bytes, *, commit: bool) -> None:
        self._last_send = asyncio.get_running_loop().time()
        await self._ws.send(
            json.dumps(
                {
                    "message_type": "input_audio_chunk",
                    "audio_base_64": base64.b64encode(pcm).decode(),
                    "commit": commit,
                    "sample_rate": SAMPLE_RATE,
                }
            )
        )

    async def send_audio(self, pcm: bytes) -> None:
        await self._send_chunk(pcm, commit=False)

    async def finalize(self) -> None:
        await self._send_chunk(SILENCE, commit=True)

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self._ws.close()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _receive_loop(self) -> None:
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                if msg.get("message_type") in ERRORS:
                    log.warning("elevenlabs stt: %s", msg)
                    continue
                for event in events_from_message(msg):
                    await self._on_event(event)
        except Exception:
            log.exception("elevenlabs stt receive loop ended")

    async def _keepalive_loop(self) -> None:
        # Push-to-talk leaves long gaps with no audio; a short silence keeps the socket open.
        with contextlib.suppress(Exception):
            while True:
                await asyncio.sleep(KEEPALIVE_S)
                if asyncio.get_running_loop().time() - self._last_send >= KEEPALIVE_S:
                    await self._send_chunk(SILENCE, commit=False)

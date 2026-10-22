"""ElevenLabs streaming TTS (Flash). One consistent voice for the whole session."""

from collections.abc import AsyncIterator

import httpx

from app.config import Settings


class ElevenLabsTts:
    def __init__(self, settings: Settings) -> None:
        self._voice_id = settings.elevenlabs_voice_id
        self._model = settings.tts_model
        self._speed = settings.tts_speed
        self._http = httpx.AsyncClient(
            base_url="https://api.elevenlabs.io",
            headers={"xi-api-key": settings.elevenlabs_api_key},
            timeout=httpx.Timeout(30.0),
        )

    async def synthesize(self, sentence: str) -> AsyncIterator[bytes]:
        body = {
            "text": sentence,
            "model_id": self._model,
            "voice_settings": {"stability": 0.55, "similarity_boost": 0.75, "speed": self._speed},
        }
        async with self._http.stream(
            "POST",
            f"/v1/text-to-speech/{self._voice_id}/stream",
            params={"output_format": "pcm_16000"},
            json=body,
        ) as response:
            if response.status_code >= 400:
                detail = (await response.aread()).decode(errors="replace")[:200]
                raise RuntimeError(f"ElevenLabs TTS {response.status_code}: {detail}")
            leftover = b""
            async for chunk in response.aiter_bytes(3200):
                data = leftover + chunk
                even = len(data) // 2 * 2  # keep 16-bit samples aligned across chunks
                leftover = data[even:]
                if even:
                    yield data[:even]

    async def aclose(self) -> None:
        await self._http.aclose()

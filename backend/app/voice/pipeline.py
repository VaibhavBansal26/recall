from collections.abc import AsyncIterator

from app.config import Settings
from app.voice.provider import SttCallback, SttSession, VoiceProvider
from app.voice.stt_deepgram import DeepgramStt
from app.voice.tts_elevenlabs import ElevenLabsTts


class PipelineVoiceProvider(VoiceProvider):
    """Browser mic -> Deepgram streaming STT ... ElevenLabs streaming TTS -> browser."""

    name = "pipeline"
    audio_input = True

    def __init__(self, settings: Settings) -> None:
        missing = [
            name
            for name, value in (
                ("DEEPGRAM_API_KEY", settings.deepgram_api_key),
                ("ELEVENLABS_API_KEY", settings.elevenlabs_api_key),
                ("ELEVENLABS_VOICE_ID", settings.elevenlabs_voice_id),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"VOICE_PROVIDER=pipeline needs {', '.join(missing)}")
        self._settings = settings
        self._tts = ElevenLabsTts(settings)

    async def open_stt(self, *, silence_ms: int, on_event: SttCallback) -> SttSession:
        return await DeepgramStt.connect(self._settings, silence_ms=silence_ms, on_event=on_event)

    def synthesize(self, sentence: str, speed: float | None = None) -> AsyncIterator[bytes]:
        return self._tts.synthesize(sentence, speed)

    async def aclose(self) -> None:
        await self._tts.aclose()

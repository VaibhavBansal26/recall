from collections.abc import AsyncIterator

from app.voice.provider import SttCallback, SttSession, VoiceProvider

SAMPLE_RATE = 16_000
SILENCE_100MS = b"\x00\x00" * (SAMPLE_RATE // 10)


class FakeVoiceProvider(VoiceProvider):
    """Typed text only, canned audio. Lets every non-voice feature run without API keys."""

    name = "fake"
    audio_input = False

    async def open_stt(self, *, silence_ms: int, on_event: SttCallback) -> SttSession:
        raise RuntimeError("FakeVoiceProvider has no speech input; use typed text")

    async def synthesize(self, sentence: str) -> AsyncIterator[bytes]:
        yield SILENCE_100MS

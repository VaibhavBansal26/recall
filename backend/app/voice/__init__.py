from app.config import Settings
from app.voice.fake import FakeVoiceProvider
from app.voice.provider import VoiceProvider


def get_voice_provider(settings: Settings) -> VoiceProvider:
    if settings.voice_provider == "fake":
        return FakeVoiceProvider()
    if settings.voice_provider == "pipeline":
        from app.voice.pipeline import PipelineVoiceProvider

        return PipelineVoiceProvider(settings)
    raise NotImplementedError("VOICE_PROVIDER=realtime is not built yet (Phase 6)")

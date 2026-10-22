from app.config import Settings
from app.llm.client import LLMClient, ModelKind, UsageTracker
from app.llm.fake import FakeLLM

__all__ = ["LLMClient", "ModelKind", "UsageTracker", "get_llm"]


def get_llm(settings: Settings, usage: UsageTracker) -> LLMClient:
    if settings.llm_provider == "fake":
        return FakeLLM(usage, delay_s=settings.fake_delay_s)
    from app.llm.anthropic_client import AnthropicLLM

    return AnthropicLLM(settings, usage)

import time
import uuid
from collections.abc import AsyncIterator

import anthropic
from pydantic import ValidationError

from app.config import Settings
from app.llm.client import LLMClient, ModelKind, T, UsageTracker


class AnthropicLLM(LLMClient):
    def __init__(self, settings: Settings, usage: UsageTracker) -> None:
        if not settings.anthropic_api_key:
            raise ValueError("LLM_PROVIDER=anthropic needs ANTHROPIC_API_KEY")
        if not (settings.llm_fast_model and settings.llm_deep_model):
            raise ValueError("LLM_PROVIDER=anthropic needs LLM_FAST_MODEL and LLM_DEEP_MODEL")
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._models: dict[ModelKind, str] = {
            "fast": settings.llm_fast_model,
            "deep": settings.llm_deep_model,
        }
        self._usage = usage

    async def complete_structured(
        self,
        kind: ModelKind,
        *,
        system: str,
        user: str,
        schema: type[T],
        session_id: uuid.UUID | None = None,
    ) -> T:
        model = self._models[kind]
        messages: list[anthropic.types.MessageParam] = [{"role": "user", "content": user}]
        last_error: ValidationError | None = None
        for _attempt in range(2):
            started = time.perf_counter()
            response = await self._client.messages.create(
                model=model,
                max_tokens=2048,
                system=system,
                messages=messages,
                tools=[
                    {
                        "name": "respond",
                        "description": "Return the structured result.",
                        "input_schema": schema.model_json_schema(),
                    }
                ],
                tool_choice={"type": "tool", "name": "respond"},
            )
            self._usage.record(
                session_id=session_id,
                model=model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
            payload = next((b.input for b in response.content if b.type == "tool_use"), {})
            try:
                return schema.model_validate(payload)
            except ValidationError as exc:
                last_error = exc
                messages = [
                    *messages,
                    {"role": "assistant", "content": response.content},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": next(
                                    b.id for b in response.content if b.type == "tool_use"
                                ),
                                "is_error": True,
                                "content": f"Invalid output, fix and retry: {exc}",
                            }
                        ],
                    },
                ]
        assert last_error is not None
        raise last_error

    async def stream_text(
        self,
        kind: ModelKind,
        *,
        system: str,
        user: str,
        session_id: uuid.UUID | None = None,
        purpose: str = "ack",
    ) -> AsyncIterator[str]:
        model = self._models[kind]
        started = time.perf_counter()
        async with self._client.messages.stream(
            model=model,
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            async for token in stream.text_stream:
                yield token
            final = await stream.get_final_message()
        self._usage.record(
            session_id=session_id,
            model=model,
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
            latency_ms=(time.perf_counter() - started) * 1000,
        )

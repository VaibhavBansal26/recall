from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import pytest
from pydantic import BaseModel

from app.config import Settings
from app.llm.anthropic_client import AnthropicLLM
from app.llm.client import UsageTracker


class Answer(BaseModel):
    value: int


def bad_request(message: str) -> anthropic.BadRequestError:
    response = httpx.Response(400, request=httpx.Request("POST", "http://x"))
    return anthropic.BadRequestError(message, response=response, body=None)


def reply(*blocks: Any) -> Any:
    usage = SimpleNamespace(input_tokens=1, output_tokens=1)
    return SimpleNamespace(content=list(blocks), usage=usage)


def tool_use(payload: dict[str, Any]) -> Any:
    return SimpleNamespace(type="tool_use", input=payload, id="t1")


class Script:
    """Stands in for `client.messages.create`: raises or returns what it is told, records calls."""

    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def llm(script: Script) -> AnthropicLLM:
    settings = Settings(anthropic_api_key="k", llm_fast_model="fast-m", llm_deep_model="deep-m")  # type: ignore[arg-type]
    client = AnthropicLLM(settings, UsageTracker())
    client._client = SimpleNamespace(messages=script)  # type: ignore[assignment]
    return client


async def ask(client: AnthropicLLM) -> Answer:
    return await client.complete_structured("deep", system="sys", user="u", schema=Answer)


@pytest.mark.anyio
async def test_a_forced_tool_call_is_used_when_the_model_allows_it() -> None:
    script = Script(reply(tool_use({"value": 3})))
    assert (await ask(llm(script))).value == 3
    assert script.calls[0]["tool_choice"] == {"type": "tool", "name": "respond"}


@pytest.mark.anyio
async def test_a_model_that_refuses_forced_tools_is_retried_with_auto_and_remembered() -> None:
    refusal = bad_request('tool_choice: type "tool" and "any" are not supported for this model.')
    script = Script(refusal, reply(tool_use({"value": 5})), reply(tool_use({"value": 6})))
    client = llm(script)
    assert (await ask(client)).value == 5
    assert script.calls[1]["tool_choice"] == {"type": "auto"}
    assert "calling the respond tool" in script.calls[1]["system"]
    assert (await ask(client)).value == 6
    assert script.calls[2]["tool_choice"] == {"type": "auto"}  # no second refusal round trip


@pytest.mark.anyio
async def test_other_bad_requests_are_not_swallowed() -> None:
    with pytest.raises(anthropic.BadRequestError):
        await ask(llm(Script(bad_request("max_tokens too large"))))


@pytest.mark.anyio
async def test_a_text_only_answer_is_asked_again_through_the_tool() -> None:
    text = SimpleNamespace(type="text", text="Sure: 7")
    script = Script(reply(text), reply(tool_use({"value": 7})))
    assert (await ask(llm(script))).value == 7
    assert script.calls[1]["messages"][-1]["content"] == "Answer by calling the respond tool."

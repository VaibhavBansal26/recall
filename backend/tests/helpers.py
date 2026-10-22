import uuid
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel

from app.llm.client import LLMClient, ModelKind, T


class ScriptedLLM(LLMClient):
    """Returns queued structured responses in order and records every prompt it was given."""

    def __init__(self, *responses: BaseModel) -> None:
        self.responses = list(responses)
        self.users: list[str] = []

    async def complete_structured(
        self,
        kind: ModelKind,
        *,
        system: str,
        user: str,
        schema: type[T],
        session_id: uuid.UUID | None = None,
    ) -> T:
        self.users.append(user)
        response: Any = self.responses.pop(0)
        assert isinstance(response, schema)
        return response

    async def stream_text(
        self, kind: ModelKind, *, system: str, user: str, session_id: uuid.UUID | None = None
    ) -> AsyncIterator[str]:
        raise NotImplementedError
        yield ""  # pragma: no cover

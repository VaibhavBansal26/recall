import logging
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, TypeVar

from pydantic import BaseModel

log = logging.getLogger(__name__)

# "fast" = live voice turns, "deep" = note structuring, diagrams, ingestion.
ModelKind = Literal["fast", "deep"]

T = TypeVar("T", bound=BaseModel)


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0


class UsageTracker:
    """Simple per-session cost counter: token and latency totals per session."""

    def __init__(self) -> None:
        self._by_session: dict[uuid.UUID | None, Usage] = defaultdict(Usage)

    def record(
        self,
        *,
        session_id: uuid.UUID | None,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
    ) -> None:
        usage = self._by_session[session_id]
        usage.calls += 1
        usage.input_tokens += input_tokens
        usage.output_tokens += output_tokens
        usage.latency_ms += latency_ms
        log.info(
            "llm call model=%s in=%d out=%d latency_ms=%.0f session=%s",
            model,
            input_tokens,
            output_tokens,
            latency_ms,
            session_id,
        )

    def for_session(self, session_id: uuid.UUID) -> Usage:
        return self._by_session[session_id]


class LLMClient(ABC):
    @abstractmethod
    async def complete_structured(
        self,
        kind: ModelKind,
        *,
        system: str,
        user: str,
        schema: type[T],
        session_id: uuid.UUID | None = None,
    ) -> T:
        """Return `schema` parsed from the model's JSON. Retries once on invalid output."""

    @abstractmethod
    def stream_text(
        self,
        kind: ModelKind,
        *,
        system: str,
        user: str,
        session_id: uuid.UUID | None = None,
    ) -> AsyncIterator[str]:
        """Yield text tokens as they arrive."""

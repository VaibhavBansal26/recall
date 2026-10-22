"""Deterministic stand-in for the LLM so everything runs and tests without API keys."""

import asyncio
import re
import uuid
from collections.abc import AsyncIterator

from app.agent.schemas import (
    CandidateNote,
    DiagramDraft,
    ExtractedNotes,
    LinkProposal,
    LinkProposals,
    MergeResult,
)
from app.llm.client import LLMClient, ModelKind, T, UsageTracker

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _q(text: str) -> str:
    return text.replace('"', "'")


class FakeLLM(LLMClient):
    def __init__(self, usage: UsageTracker, delay_s: float = 0.0) -> None:
        self._usage = usage
        self._delay_s = delay_s

    async def complete_structured(
        self,
        kind: ModelKind,
        *,
        system: str,
        user: str,
        schema: type[T],
        session_id: uuid.UUID | None = None,
    ) -> T:
        self._usage.record(
            session_id=session_id, model="fake", input_tokens=0, output_tokens=0, latency_ms=0
        )
        if schema is ExtractedNotes:
            latest = user.split("LATEST:\n", 1)[-1]
            notes = [
                CandidateNote(title=s.strip().rstrip(".!?")[:80], body_md=s.strip())
                for s in _SENTENCE.split(latest)
                if len(s.split()) >= 4
            ]
            return schema.model_validate(ExtractedNotes(notes=notes).model_dump())
        if schema is MergeResult:
            existing = user.split("EXISTING:\n", 1)[1].split("\nNEW:\n", 1)[0].strip()
            new = user.split("\nNEW:\n", 1)[1].strip()
            body = existing if new in existing else f"{existing} {new}"
            return schema.model_validate(MergeResult(body_md=body).model_dump())
        if schema is DiagramDraft:
            title = user.split("TITLE: ", 1)[1].split("\nBODY:", 1)[0]
            body = user.split("\nBODY:\n", 1)[1].split("\n\nYour previous", 1)[0]
            steps = [s.strip() for s in _SENTENCE.split(body) if s.strip()][:5]
            lines = ["flowchart TD", f'    N0["{_q(title)}"]']
            for i, step in enumerate(steps, 1):
                lines.append(f'    N{i}["{_q(step)}"]')
                lines.append(f"    N{i - 1} --> N{i}")
            return schema.model_validate(
                DiagramDraft(mermaid="\n".join(lines), steps=steps).model_dump()
            )
        if schema is LinkProposals:
            count = len(re.findall(r"^\[\d+\] ", user, re.MULTILINE))
            links = [
                LinkProposal(candidate=i, kind="related", direction="to")
                for i in range(1, count + 1)
            ]
            return schema.model_validate(LinkProposals(links=links).model_dump())
        raise NotImplementedError(f"FakeLLM has no handler for {schema.__name__}")

    async def stream_text(
        self,
        kind: ModelKind,
        *,
        system: str,
        user: str,
        session_id: uuid.UUID | None = None,
    ) -> AsyncIterator[str]:
        self._usage.record(
            session_id=session_id, model="fake", input_tokens=0, output_tokens=0, latency_ms=0
        )
        for token in ("Got it, noted. ", "Keep going."):
            await asyncio.sleep(self._delay_s)
            yield token

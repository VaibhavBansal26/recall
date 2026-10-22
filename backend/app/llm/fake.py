"""Deterministic stand-in for the LLM so everything runs and tests without API keys."""

import asyncio
import re
import uuid
from collections.abc import AsyncIterator

from app.agent.router import Mode, RouteDecision
from app.agent.schemas import (
    CandidateNote,
    DiagramDraft,
    ExtractedNotes,
    LinkProposal,
    LinkProposals,
    MergeResult,
    QuizTurn,
    ReviewDraft,
    ReviewDrafts,
    WhyMatters,
)
from app.llm.client import LLMClient, ModelKind, T, UsageTracker

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _field(user: str, key: str) -> str:
    """Value of a `KEY: value` field in a multi-line prompt (up to the next ALL-CAPS key)."""
    m = re.search(rf"^{re.escape(key)}:[ \t]*(.*?)(?=^[A-Z][A-Z ]+:|\Z)", user, re.S | re.M)
    return m.group(1).strip() if m else ""


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 4}


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
        if schema is ReviewDrafts:
            title, body = _field(user, "NOTE TITLE"), _field(user, "NOTE BODY")
            drafts = []
            words = sorted({w for w in re.findall(r"[A-Za-z]{5,}", body)}, key=len, reverse=True)
            if words:
                blank = body.replace(words[0], "_____", 1)
                drafts.append(ReviewDraft(kind="cloze", prompt=blank.strip(), answer=words[0]))
            drafts.append(
                ReviewDraft(
                    kind="question", prompt=f"What do you know about: {title}?", answer=body
                )
            )
            return schema.model_validate(ReviewDrafts(items=drafts).model_dump())
        if schema is QuizTurn:
            expected, given = _field(user, "EXPECTED ANSWER"), _field(user, "ANSWER")
            need = _content_words(expected)
            hit = len(need & _content_words(given)) / len(need) if need else 0.0
            correct = bool(given) and hit >= 0.6
            tier = int(_field(user, "HINT TIER") or 1)
            title, body = _field(user, "NOTE TITLE"), _field(user, "NOTE BODY")
            hint = ""
            if not correct:
                if tier <= 1:
                    hint = f"Think about this idea: {title}. Take another go."
                elif tier == 2:
                    hint = "It starts like this: " + " ".join(expected.split()[:3]) + "."
                else:
                    hint = (
                        f"The answer is {expected}. To put it plainly, {body} "
                        "Can you say that back in your own words?"
                    )
            return schema.model_validate(
                QuizTurn(
                    correct=correct,
                    partial=bool(given) and not correct and hit >= 0.3,
                    missing_points=[] if correct else sorted(need - _content_words(given))[:3],
                    spoken_hint=hint,
                ).model_dump()
            )
        if schema is WhyMatters:
            return schema.model_validate(
                WhyMatters(
                    line="This matters because it connects to the rest of what you know."
                ).model_dump()
            )
        if schema is RouteDecision:
            return schema.model_validate(RouteDecision(mode=Mode.capture).model_dump())
        if schema is DiagramDraft and user.startswith("TOPIC:"):
            topic = _field(user, "TOPIC")
            lines = ["flowchart TD", f'    T["{_q(topic)}"]']
            beats = ["What it is", "How it works", "Why it matters", "Its impact"]
            for i, beat in enumerate(beats, 1):
                lines += [f'    B{i}["{beat}"]', f"    {'T' if i == 1 else f'B{i - 1}'} --> B{i}"]
            return schema.model_validate(
                DiagramDraft(mermaid="\n".join(lines), steps=beats).model_dump()
            )
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
        purpose: str = "ack",
    ) -> AsyncIterator[str]:
        self._usage.record(
            session_id=session_id, model="fake", input_tokens=0, output_tokens=0, latency_ms=0
        )
        topic = _field(user, "TOPIC") or user.strip()
        scripts = {
            "ack": ("Got it, noted. ", "Keep going."),
            "explain": (
                f"First, what it is: {topic} is an idea worth knowing. ",
                "Next, how it works: it follows a few simple steps. ",
                "That matters because it changes how you build things. ",
                "In practice, the impact is better results. Ask me anything.",
            ),
            "explain_simple": (
                "Okay, let's take it slowly. ",
                f"Step one, think of {topic} like something from everyday life. ",
                "Does that make sense?",
            ),
            "chitchat": ("Happy to help. ", "Shall we get back to learning?"),
        }
        for token in scripts.get(purpose, scripts["ack"]):
            await asyncio.sleep(self._delay_s)
            yield token

"""Check a spoken explanation against the learner's own notes or source.

The checker is kept honest: a claimed contradiction only counts if the quoted words were
really said.
"""

import re
import uuid
from dataclasses import dataclass, field

from app.agent.prompts import load_prompt
from app.agent.schemas import AccuracyCheck, Contradiction
from app.llm.client import LLMClient
from app.services.reference import Reference

MAX_MISSED = 5


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


@dataclass
class Accuracy:
    against: str
    covered: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    contradicted: list[Contradiction] = field(default_factory=list)
    verdict: str = ""

    def spoken(self) -> str:
        parts = [f"Checking against {self.against}."]
        if self.covered:
            parts.append(f"You covered {_join(self.covered[:3])}.")
        if self.contradicted:
            c = self.contradicted[0]
            parts.append(
                f"One thing to check: you said {c.said}, but your notes say {c.reference}."
            )
        if self.missed:
            parts.append(f"You didn't mention {_join(self.missed[:3])}.")
        if not (self.covered or self.missed or self.contradicted) and self.verdict:
            parts.append(self.verdict)
        return " ".join(parts)


def _join(items: list[str]) -> str:
    items = [i.strip().rstrip(".") for i in items if i.strip()]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def validate(raw: AccuracyCheck, transcript: str, against: str) -> Accuracy:
    said = _norm(transcript)
    real = [
        c
        for c in raw.contradicted
        if c.said.strip() and c.reference.strip() and _norm(c.said) in said
    ]
    return Accuracy(
        against=against,
        covered=[c for c in raw.covered if c.strip()][:6],
        missed=[m for m in raw.missed if m.strip()][:MAX_MISSED],
        contradicted=real[:3],
        verdict=raw.verdict.strip(),
    )


async def check(
    llm: LLMClient,
    *,
    topic: str,
    transcript: str,
    reference: Reference,
    session_id: uuid.UUID | None = None,
) -> Accuracy:
    raw = await llm.complete_structured(
        "deep",
        system=load_prompt("accuracy_check").text,
        user=f"TOPIC: {topic}\nREFERENCE:\n{reference.text}\n\nLEARNER SAID:\n{transcript}",
        schema=AccuracyCheck,
        session_id=session_id,
    )
    return validate(raw, transcript, reference.about())

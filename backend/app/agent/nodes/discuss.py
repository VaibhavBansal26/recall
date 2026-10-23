"""Discuss: work through a design or problem out loud. The assistant suggests, then evaluates.

The learner's own words are still captured as notes (Problem / Approach / Tradeoff / Decision, per
the solutions track), filed in the discussion's notebook. What the assistant adds is never stored as
the learner's: the wrap-up evaluation is saved as an unconfirmed assistant note.
"""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from app.agent.deps import AgentDeps
from app.agent.prompts import load_prompt
from app.agent.schemas import DiscussionSummary
from app.db.models import Note
from app.tracks import guidance_for

HISTORY_TURNS = 8


@dataclass
class DiscussSession:
    problem: str
    notebook_id: uuid.UUID
    notebook_name: str
    turns: int = 0
    generic: bool = False  # the learner has not said which problem yet
    history: list[tuple[str, str]] = field(default_factory=list)  # ("learner" | "you", text)

    def transcript(self) -> str:
        recent = self.history[-HISTORY_TURNS * 2 :]
        return "\n".join(f"{who}: {text}" for who, text in recent) or "(nothing yet)"


async def stream_turn(
    deps: AgentDeps,
    ds: DiscussSession,
    *,
    session_id: uuid.UUID,
    track: str,
    learner_text: str | None,
) -> AsyncIterator[str]:
    """The assistant's spoken reply: an opening question, or an evaluation plus a suggestion."""
    stage = "continue" if learner_text else ("choose" if ds.generic else "open")
    user = (
        f"PROBLEM: {ds.problem}\nSTAGE: {stage}\n"
        f"CONVERSATION SO FAR:\n{ds.transcript()}\n"
        f"LEARNER JUST SAID: {learner_text or '(nothing yet)'}"
    )
    if learner_text:
        ds.history.append(("learner", learner_text))
    spoken: list[str] = []
    async for token in deps.llm.stream_text(
        "fast",
        system=load_prompt("discuss_turn").text + guidance_for(track, "explain"),
        user=user,
        session_id=session_id,
        purpose="discuss",
    ):
        spoken.append(token)
        yield token
    ds.history.append(("you", " ".join(t.strip() for t in spoken if t.strip())))
    ds.turns += 1


async def summarize(
    deps: AgentDeps, ds: DiscussSession, notes: list[Note], *, session_id: uuid.UUID
) -> DiscussionSummary:
    saved = "\n".join(f"- {n.title}: {n.body_md}" for n in notes) or "(no notes were saved)"
    return await deps.llm.complete_structured(
        "deep",
        system=load_prompt("discuss_summary").text,
        user=f"PROBLEM: {ds.problem}\nNOTES:\n{saved}\nCONVERSATION:\n{ds.transcript()}",
        schema=DiscussionSummary,
        session_id=session_id,
    )

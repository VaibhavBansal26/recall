"""Explain: what / how / why / impact, spoken in short sentences, with a diagram alongside."""

import uuid
from collections.abc import AsyncIterator

from app.agent.deps import AgentDeps
from app.agent.prompts import load_prompt
from app.db.models import DiagramKind, Note
from app.services import retrieval
from app.services.diagrams import build_diagram
from app.tracks import guidance_for


async def find_related_note(deps: AgentDeps, track: str, topic: str) -> Note | None:
    """The learner's own note on this topic, if they have one, to ground the explanation."""
    async with deps.sessionmaker() as db:
        found = await retrieval.hybrid_search(
            db, deps.embedder, track_slug=track, query=topic, limit=1
        )
    return found[0] if found else None


def _user_message(topic: str, note: Note | None) -> str:
    message = f"TOPIC: {topic}"
    if note is not None:
        message += f"\nLEARNER NOTE: {note.title}. {note.body_md}"
    return message


def explain_stream(
    deps: AgentDeps,
    *,
    session_id: uuid.UUID,
    topic: str,
    simple: bool,
    note: Note | None,
    track: str,
) -> AsyncIterator[str]:
    """Spoken explanation tokens. `simple` is the "I don't get it" version (rule 4)."""
    name = "explain_simple" if simple else "explain"
    return deps.llm.stream_text(
        "fast",
        system=load_prompt(name).text + guidance_for(track, "explain"),
        user=_user_message(topic, note),
        session_id=session_id,
        purpose=name,
    )


async def explain_diagram(
    deps: AgentDeps, *, session_id: uuid.UUID, topic: str, note: Note | None, track: str
) -> tuple[DiagramKind, str]:
    """The diagram that accompanies an explanation (always produced, never words alone)."""
    return await build_diagram(
        deps.llm,
        title=topic,
        body_md=note.body_md if note else topic,
        session_id=session_id,
        prompt_name="diagram_explain",
        user=_user_message(topic, note),
        track_slug=track,
    )

"""Aria: one persona and a live view of the learner's library, shared by every spoken reply."""

import uuid

from app.agent.deps import AgentDeps
from app.agent.prompts import load_prompt
from app.services import library

NAME = "Aria"


async def system_for(
    deps: AgentDeps, base: str, *, track: str, notebook_id: uuid.UUID | None = None
) -> str:
    """The persona, then what Aria can see in the learner's notebooks right now, then the task."""
    async with deps.sessionmaker() as db:
        snap = await library.snapshot(db, track, notebook_id)
    return f"{load_prompt('aria').text}\n\nLIBRARY (right now):\n{snap.render()}\n\n{base}"

"""Draft: when the learner says "write the notes", Aria writes starter notes on the topic.

Rule 6: these are the assistant's own, so they are stored with origin "assistant", unconfirmed,
and shown differently until the learner accepts them.
"""

import uuid

from app.agent.deps import AgentDeps
from app.agent.prompts import load_prompt
from app.agent.schemas import CandidateNote, DraftedNotes
from app.tracks import guidance_for

MAX_DRAFT_NOTES = 7


async def draft_notes(
    deps: AgentDeps, *, topic: str, track_name: str, track: str, session_id: uuid.UUID
) -> list[CandidateNote]:
    drafted = await deps.llm.complete_structured(
        "deep",
        system=load_prompt("draft_notes").text + guidance_for(track, "capture"),
        user=f"TOPIC: {topic}\nTRACK: {track_name}",
        schema=DraftedNotes,
        session_id=session_id,
    )
    seen: set[str] = set()
    out: list[CandidateNote] = []
    for note in drafted.notes:
        key = note.title.strip().lower()
        if note.title.strip() and note.body_md.strip() and key not in seen:
            seen.add(key)
            out.append(note)
    return out[:MAX_DRAFT_NOTES]

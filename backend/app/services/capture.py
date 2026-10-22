"""File one candidate note: create it, or merge it into the closest existing note instead.

Shared by live capture (what the learner said) and ingestion (what a source said), so both
dedupe and merge identically and both are undoable through a CaptureEvent.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.deps import AgentDeps
from app.agent.prompts import load_prompt
from app.agent.schemas import MergeResult
from app.db.models import CaptureAction, CaptureEvent, Note, NoteOrigin, Track
from app.services import notes as notes_svc


async def file_candidate(
    deps: AgentDeps,
    db: AsyncSession,
    *,
    track: Track,
    title: str,
    body_md: str,
    embedding: list[float],
    origin: NoteOrigin,
    session_id: uuid.UUID | None = None,
    source_id: uuid.UUID | None = None,
    usage_id: uuid.UUID | None = None,
) -> tuple[CaptureEvent, Note]:
    dup = await notes_svc.find_duplicate(
        db, track.id, title, embedding, deps.settings.dedup_similarity
    )
    if dup is None:
        note, event = await notes_svc.create_note(
            db,
            track=track,
            title=title,
            body_md=body_md,
            origin=origin,
            embedding=embedding,
            session_id=session_id,
            source_id=source_id,
        )
        assert event is not None and event.action == CaptureAction.created
        return event, note

    existing, similarity = dup
    merged = await deps.llm.complete_structured(
        "deep",
        system=load_prompt("capture_merge").text,
        user=f"EXISTING:\n{existing.body_md}\nNEW:\n{body_md}",
        schema=MergeResult,
        session_id=usage_id or session_id,
    )
    event = await notes_svc.merge_into(
        db,
        note=existing,
        body_md=merged.body_md,
        embedding=embedding,
        similarity=similarity,
        session_id=session_id,
        source_id=source_id,
    )
    return event, existing

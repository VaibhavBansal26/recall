import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LOCAL_USER_ID
from app.db.models import CaptureAction, CaptureEvent, Note, NoteOrigin, Track


async def get_note(db: AsyncSession, note_id: uuid.UUID) -> Note | None:
    return (await db.execute(select(Note).where(Note.id == note_id))).scalar_one_or_none()


async def list_notes(
    db: AsyncSession, track_slug: str | None = None, limit: int = 200
) -> list[Note]:
    query = select(Note).order_by(Note.created_at.desc()).limit(limit)
    if track_slug:
        query = query.join(Track, Track.id == Note.track_id).where(Track.slug == track_slug)
    return list((await db.execute(query)).scalars())


async def find_duplicate(
    db: AsyncSession,
    track_id: uuid.UUID,
    title: str,
    embedding: list[float],
    threshold: float,
) -> tuple[Note, float] | None:
    """Closest existing note in the track: same title, or cosine similarity above `threshold`."""
    same_title = (
        await db.execute(
            select(Note)
            .where(Note.track_id == track_id, func.lower(Note.title) == title.strip().lower())
            .limit(1)
        )
    ).scalar_one_or_none()
    if same_title is not None:
        return same_title, 1.0

    distance = Note.embedding.cosine_distance(embedding)
    row = (
        await db.execute(
            select(Note, distance.label("distance"))
            .where(Note.track_id == track_id, Note.embedding.is_not(None))
            .order_by(distance)
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    note, dist = row
    similarity = 1.0 - float(dist)
    return (note, similarity) if similarity > threshold else None


async def create_note(
    db: AsyncSession,
    *,
    track: Track,
    title: str,
    body_md: str,
    origin: NoteOrigin,
    embedding: list[float] | None,
    session_id: uuid.UUID | None = None,
    source_id: uuid.UUID | None = None,
    notebook_id: uuid.UUID | None = None,
    record_event: bool = True,
) -> tuple[Note, CaptureEvent | None]:
    note = Note(
        user_id=LOCAL_USER_ID,
        track_id=track.id,
        track=track,
        title=title,
        body_md=body_md,
        origin=origin,
        confirmed=origin == NoteOrigin.user,  # the user said it, so nothing to confirm
        embedding=embedding,
        source_id=source_id,
        notebook_id=notebook_id,
    )
    db.add(note)
    await db.flush()
    event = None
    if record_event:
        event = CaptureEvent(
            session_id=session_id,
            source_id=source_id,
            note_id=note.id,
            action=CaptureAction.created,
            note=note,
        )
        db.add(event)
    await db.commit()
    return note, event


async def merge_into(
    db: AsyncSession,
    *,
    note: Note,
    body_md: str,
    embedding: list[float],
    similarity: float,
    session_id: uuid.UUID | None = None,
    source_id: uuid.UUID | None = None,
) -> CaptureEvent:
    event = CaptureEvent(
        session_id=session_id,
        source_id=source_id,
        note_id=note.id,
        action=CaptureAction.merged,
        similarity=similarity,
        before={
            "title": note.title,
            "body_md": note.body_md,
            "embedding": [float(x) for x in note.embedding] if note.embedding is not None else None,
        },
        note=note,
    )
    note.body_md = body_md
    note.embedding = embedding
    db.add(event)
    await db.commit()
    return event


async def update_note(
    db: AsyncSession,
    note: Note,
    *,
    title: str | None = None,
    body_md: str | None = None,
    confirmed: bool | None = None,
    fragile: bool | None = None,
    embedding: list[float] | None = None,
    notebook_id: uuid.UUID | None | object = ...,
) -> Note:
    if title is not None:
        note.title = title
    if body_md is not None:
        note.body_md = body_md
    if confirmed is not None:
        note.confirmed = confirmed
    if fragile is not None:
        note.fragile = fragile
    if embedding is not None:
        note.embedding = embedding
    if notebook_id is not ...:
        note.notebook_id = notebook_id  # type: ignore[assignment]
    note.updated_at = datetime.now(UTC)
    await db.commit()
    return note


async def undo_capture(db: AsyncSession, event_id: uuid.UUID) -> CaptureEvent | None:
    """Revert a capture event: delete a created note, or restore a merged note's prior state."""
    event = (
        await db.execute(select(CaptureEvent).where(CaptureEvent.id == event_id))
    ).scalar_one_or_none()
    if event is None or event.undone:
        return event
    note = event.note
    if note is not None:
        if event.action == CaptureAction.created:
            await db.delete(note)
        elif event.before is not None:
            note.title = event.before["title"]
            note.body_md = event.before["body_md"]
            note.embedding = event.before["embedding"]
            note.updated_at = datetime.now(UTC)
    event.undone = True
    await db.commit()
    return event

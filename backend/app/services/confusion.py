import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConfusionEvent
from app.services import notes as notes_svc


async def log_confusion(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    note_id: uuid.UUID | None,
    trigger: str,
) -> ConfusionEvent:
    """Record a confusion event and mark the related note fragile (no manual flagging needed)."""
    event = ConfusionEvent(session_id=session_id, note_id=note_id, trigger=trigger)
    db.add(event)
    if note_id is not None:
        note = await notes_svc.get_note(db, note_id)
        if note is not None:
            note.fragile = True
    await db.commit()
    return event

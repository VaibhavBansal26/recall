import uuid

from fastapi import APIRouter, HTTPException
from fsrs import Rating

from app.api.deps import Db
from app.db.models import ReviewItem
from app.schemas import DueOut, GradeIn, GradeOut, ReviewItemOut
from app.services import reviews as svc

router = APIRouter(prefix="/api")

_RATINGS = {"again": Rating.Again, "hard": Rating.Hard, "good": Rating.Good, "easy": Rating.Easy}


def to_item_out(item: ReviewItem) -> ReviewItemOut:
    return ReviewItemOut(
        id=item.id,
        note_id=item.note_id,
        note_title=item.note.title,
        kind=item.prompt_kind,
        prompt=item.prompt,
        due_at=item.due_at,
        last_reviewed_at=item.last_reviewed_at,
        fragile=item.fragile,
        retrievability=svc.retrievability(item),
    )


@router.get("/reviews/due", response_model=DueOut)
async def due(db: Db, track: str | None = None, limit: int = 20) -> DueOut:
    """What is due now, most overdue first. The answer is never included."""
    items = await svc.due_items(db, track_slug=track, limit=max(1, min(limit, 100)))
    return DueOut(
        total_due=await svc.count_due(db, track_slug=track),
        next_due_at=await svc.next_due_at(db, track_slug=track),
        items=[to_item_out(i) for i in items],
    )


@router.post("/reviews/{item_id}/grade", response_model=GradeOut)
async def grade(item_id: uuid.UUID, body: GradeIn, db: Db) -> GradeOut:
    item = await svc.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    outcome = await svc.grade_item(
        db,
        item,
        _RATINGS[body.grade],
        hint_tier=body.hint_tier_used,
        latency_ms=body.latency_ms,
    )
    return GradeOut(
        item=to_item_out(outcome.item),
        grade=body.grade,
        became_fragile=outcome.became_fragile,
        cleared_fragile=outcome.cleared_fragile,
        next_due_at=outcome.due_at,
    )

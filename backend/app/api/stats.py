from datetime import UTC, datetime

from fastapi import APIRouter

from app.api.briefs import user_tz
from app.api.deps import Db
from app.schemas import ArticulationPoint, RetentionPoint, StatsOut, WeakNodeOut
from app.services import articulation as articulation_svc
from app.services.stats import compute_stats

router = APIRouter(prefix="/api")


@router.get("/stats", response_model=StatsOut)
async def stats(db: Db, track: str | None = None) -> StatsOut:
    """Due, retention, streaks, weakest notes. Read-only, so n8n's nudge may call it too."""
    now, tz = datetime.now(UTC), user_tz()
    s = await compute_stats(db, track_slug=track, now=now, tz=tz)
    trend = await articulation_svc.trend(db, now=now, tz=tz)
    return StatsOut(
        due_now=s.due_now,
        due_today=s.due_today,
        next_due_at=s.next_due_at,
        items_total=s.items_total,
        items_reviewed=s.items_reviewed,
        notes_total=s.notes_total,
        fragile_notes=s.fragile_notes,
        sources_awaiting=s.sources_awaiting,
        reviews_today=s.reviews_today,
        reviewed_today=s.reviewed_today,
        streak_current=s.streak_current,
        streak_longest=s.streak_longest,
        retention_7d=s.retention_7d,
        retention_30d=s.retention_30d,
        unaided_rate_30d=s.unaided_rate_30d,
        average_retrievability=s.average_retrievability,
        retention_curve=[
            RetentionPoint(
                date=d.day, reviews=d.reviews, recalled=d.recalled, retention=d.retention
            )
            for d in s.curve
        ],
        weak_nodes=[
            WeakNodeOut(
                note_id=w.note_id,
                title=w.note_title,
                item_id=w.item_id,
                strength=w.retrievability,
                fragile=w.fragile,
                lapses=w.lapses,
            )
            for w in s.weak
        ],
        articulation_trend=[
            ArticulationPoint(
                date=p.day,
                clarity=p.clarity,
                structure=p.structure,
                filler_rate=p.filler_rate,
                wpm=p.wpm,
                sessions=p.sessions,
            )
            for p in trend
        ],
    )

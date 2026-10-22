"""The daily brief: the notes that are slipping, one question each, then what is due today."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    BriefStatus,
    DailyBrief,
    Note,
    ReviewItem,
    ReviewLog,
    Track,
)
from app.services import reviews as reviews_svc
from app.services.sessions import get_track
from app.services.timeutil import day_bounds, local_date

LAPSE_WINDOW = timedelta(hours=36)  # "yesterday": a miss in roughly the last day and a half
LAPSE_GRADES = (1, 2)  # Again, Hard


def weakness_score(retrievability: float | None, fragile: bool, lapses: int) -> float:
    """Higher = weaker. Forgetting (low retrievability), fragility and recent misses all count."""
    forgetting = 0.0 if retrievability is None else 1.0 - retrievability
    return forgetting + (0.5 if fragile else 0.0) + 0.25 * min(lapses, 4)


@dataclass(frozen=True)
class WeakItem:
    note_id: uuid.UUID
    note_title: str
    item_id: uuid.UUID
    retrievability: float | None
    fragile: bool
    lapses: int
    score: float


async def weakest(
    db: AsyncSession,
    *,
    track_slug: str | None,
    now: datetime,
    limit: int,
) -> list[WeakItem]:
    """The weakest notes, best candidate question for each, weakest first."""
    query = (
        select(ReviewItem)
        .join(Note, Note.id == ReviewItem.note_id)
        .where(ReviewItem.last_reviewed_at.is_not(None), Note.confirmed.is_(True))
    )
    if track_slug:
        query = query.join(Track, Track.id == Note.track_id).where(Track.slug == track_slug)
    items = list((await db.execute(query)).scalars())
    if not items:
        return []

    lapse_rows = (
        await db.execute(
            select(ReviewLog.review_item_id, func.count())
            .where(
                ReviewLog.review_item_id.in_([i.id for i in items]),
                ReviewLog.grade.in_(LAPSE_GRADES),
                ReviewLog.reviewed_at >= now - LAPSE_WINDOW,
            )
            .group_by(ReviewLog.review_item_id)
        )
    ).all()
    lapses = {item_id: int(n) for item_id, n in lapse_rows}

    best: dict[uuid.UUID, WeakItem] = {}
    for item in items:
        r = reviews_svc.retrievability(item, now)
        n = lapses.get(item.id, 0)
        candidate = WeakItem(
            note_id=item.note_id,
            note_title=item.note.title,
            item_id=item.id,
            retrievability=r,
            fragile=item.fragile or item.note.fragile,
            lapses=n,
            score=weakness_score(r, item.fragile or item.note.fragile, n),
        )
        current = best.get(item.note_id)
        if current is None or candidate.score > current.score:
            best[item.note_id] = candidate
    ranked = sorted(best.values(), key=lambda w: (-w.score, w.note_title))
    return ranked[:limit]


async def due_today_count(
    db: AsyncSession, *, track_slug: str | None, now: datetime, tz: ZoneInfo
) -> int:
    """Items due at any point before the local day ends (so the morning count is the day's work)."""
    _, end = day_bounds(local_date(now, tz), tz)
    return await reviews_svc.count_due(db, track_slug=track_slug, now=end)


async def create_brief(
    db: AsyncSession,
    *,
    track_slug: str,
    now: datetime,
    tz: ZoneInfo,
    questions: int = 3,
    force: bool = False,
) -> tuple[DailyBrief, bool]:
    """Today's brief. Calling again the same day returns it (cron-safe), unless `force`."""
    track = await get_track(db, track_slug)
    if track is None:
        raise ValueError(f"Unknown track {track_slug!r}")
    today = local_date(now, tz)

    existing = (
        await db.execute(select(DailyBrief).where(DailyBrief.brief_date == today))
    ).scalar_one_or_none()
    if existing is not None:
        if not force or existing.status in (BriefStatus.started, BriefStatus.completed):
            return existing, False
        await db.delete(existing)
        await db.flush()

    picked = await weakest(db, track_slug=track_slug, now=now, limit=questions)
    chosen = {w.note_id for w in picked}
    item_ids = [w.item_id for w in picked]
    if len(item_ids) < questions:  # fill from what is due, most overdue first
        due = await reviews_svc.due_items(db, track_slug=track_slug, now=now, limit=questions * 3)
        for item in due:
            if len(item_ids) >= questions:
                break
            if item.note_id not in chosen:
                chosen.add(item.note_id)
                item_ids.append(item.id)

    brief = DailyBrief(
        track_id=track.id,
        track=track,
        brief_date=today,
        status=BriefStatus.ready if item_ids else BriefStatus.empty,
        item_ids=[str(i) for i in item_ids],
        due_today=await due_today_count(db, track_slug=track_slug, now=now, tz=tz),
    )
    db.add(brief)
    await db.commit()
    return brief, True


async def get_brief(db: AsyncSession, brief_id: uuid.UUID) -> DailyBrief | None:
    return (
        await db.execute(select(DailyBrief).where(DailyBrief.id == brief_id))
    ).scalar_one_or_none()


async def ready_brief(db: AsyncSession, *, now: datetime, tz: ZoneInfo) -> DailyBrief | None:
    """Today's brief if it is waiting to be started (what the "ready" prompt shows)."""
    return (
        await db.execute(
            select(DailyBrief).where(
                DailyBrief.brief_date == local_date(now, tz),
                DailyBrief.status == BriefStatus.ready,
            )
        )
    ).scalar_one_or_none()


async def brief_items(db: AsyncSession, brief: DailyBrief) -> list[ReviewItem]:
    """The brief's review items in asking order (items deleted since are skipped)."""
    ids = [uuid.UUID(i) for i in brief.item_ids]
    found = {
        i.id: i
        for i in (await db.execute(select(ReviewItem).where(ReviewItem.id.in_(ids)))).scalars()
    }
    return [found[i] for i in ids if i in found]


async def mark_started(db: AsyncSession, brief: DailyBrief, session_id: uuid.UUID | None) -> None:
    if brief.status == BriefStatus.ready:
        brief.status = BriefStatus.started
        brief.started_at = datetime.now(UTC)
    brief.session_id = session_id or brief.session_id
    await db.commit()


async def mark_completed(db: AsyncSession, brief: DailyBrief) -> None:
    brief.status = BriefStatus.completed
    brief.completed_at = datetime.now(UTC)
    await db.commit()


def spoken_intro(count: int) -> str:
    topics = "topic that is slipping" if count == 1 else f"{count} topics that are slipping"
    return f"Good morning. Here's your brief: one question on each of the {topics}. "


def spoken_outro(due_today: int) -> str:
    if due_today == 0:
        return "And nothing else is due today."
    noun = "review is" if due_today == 1 else "reviews are"
    return f"And that's your brief. {due_today} {noun} due today."

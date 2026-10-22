"""Numbers for the stats screen: due, retention, streaks, weakest notes."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Note, ReviewItem, ReviewLog, Source, SourceStatus, Track
from app.services import briefs as briefs_svc
from app.services import reviews as reviews_svc
from app.services.timeutil import local_date

RECALLED_GRADES = (2, 3, 4)  # Hard, Good, Easy: the learner got there (FSRS "true retention")
HISTORY_DAYS = 120  # how far back streaks are computed


@dataclass
class DayStat:
    day: date
    reviews: int = 0
    recalled: int = 0
    unaided: int = 0

    @property
    def retention(self) -> float | None:
        return self.recalled / self.reviews if self.reviews else None


def compute_streaks(days: set[date], today: date) -> tuple[int, int]:
    """(current, longest) runs of consecutive days with a review.

    The current streak is still alive if the last review was yesterday (today is not over yet).
    """
    if not days:
        return 0, 0
    longest = run = 0
    previous: date | None = None
    for d in sorted(days):
        run = run + 1 if previous is not None and d - previous == timedelta(days=1) else 1
        longest = max(longest, run)
        previous = d

    cursor = today if today in days else today - timedelta(days=1)
    current = 0
    while cursor in days:
        current += 1
        cursor -= timedelta(days=1)
    return current, longest


def daily_series(by_day: dict[date, DayStat], today: date, days: int) -> list[DayStat]:
    """One entry per day for the last `days` days, including days with no reviews."""
    return [
        by_day.get(d) or DayStat(d)
        for d in (today - timedelta(days=n) for n in range(days - 1, -1, -1))
    ]


def window_rate(series: list[DayStat], last_days: int, *, unaided: bool = False) -> float | None:
    window = series[-last_days:]
    total = sum(d.reviews for d in window)
    if not total:
        return None
    return sum(d.unaided if unaided else d.recalled for d in window) / total


@dataclass
class Stats:
    due_now: int
    due_today: int
    next_due_at: datetime | None
    items_total: int
    items_reviewed: int
    notes_total: int
    fragile_notes: int
    sources_awaiting: int
    reviews_today: int
    reviewed_today: bool
    streak_current: int
    streak_longest: int
    retention_7d: float | None
    retention_30d: float | None
    unaided_rate_30d: float | None
    average_retrievability: float | None
    curve: list[DayStat] = field(default_factory=list)
    weak: list[briefs_svc.WeakItem] = field(default_factory=list)


async def compute_stats(
    db: AsyncSession,
    *,
    track_slug: str | None,
    now: datetime,
    tz: ZoneInfo,
    curve_days: int = 30,
) -> Stats:
    today = local_date(now, tz)

    def scoped(query: Select[Any]) -> Select[Any]:
        if track_slug:
            return query.join(Track, Track.id == Note.track_id).where(Track.slug == track_slug)
        return query

    log_query = scoped(
        select(ReviewLog)
        .join(ReviewItem, ReviewItem.id == ReviewLog.review_item_id)
        .join(Note, Note.id == ReviewItem.note_id)
        .where(ReviewLog.reviewed_at >= now - timedelta(days=HISTORY_DAYS))
    )
    by_day: dict[date, DayStat] = {}
    for log in (await db.execute(log_query)).scalars():
        d = local_date(log.reviewed_at, tz)
        stat = by_day.setdefault(d, DayStat(d))
        stat.reviews += 1
        stat.recalled += 1 if log.grade in RECALLED_GRADES else 0
        stat.unaided += 1 if log.hint_tier_used == 0 else 0
    series = daily_series(by_day, today, HISTORY_DAYS)
    current, longest = compute_streaks({d for d, s in by_day.items() if s.reviews}, today)

    items = list(
        (
            await db.execute(scoped(select(ReviewItem).join(Note, Note.id == ReviewItem.note_id)))
        ).scalars()
    )
    reviewed = [i for i in items if i.last_reviewed_at is not None]
    retrievabilities = [
        r for r in (reviews_svc.retrievability(i, now) for i in reviewed) if r is not None
    ]

    notes_total = int(
        (await db.execute(scoped(select(func.count()).select_from(Note)))).scalar_one()
    )
    fragile_notes = int(
        (
            await db.execute(
                scoped(select(func.count()).select_from(Note).where(Note.fragile.is_(True)))
            )
        ).scalar_one()
    )
    awaiting = int(
        (
            await db.execute(
                select(func.count()).select_from(Source).where(Source.status == SourceStatus.ready)
            )
        ).scalar_one()
    )

    today_stat = by_day.get(today)
    return Stats(
        due_now=await reviews_svc.count_due(db, track_slug=track_slug, now=now),
        due_today=await briefs_svc.due_today_count(db, track_slug=track_slug, now=now, tz=tz),
        next_due_at=await reviews_svc.next_due_at(db, track_slug=track_slug, now=now),
        items_total=len(items),
        items_reviewed=len(reviewed),
        notes_total=notes_total,
        fragile_notes=fragile_notes,
        sources_awaiting=awaiting,
        reviews_today=today_stat.reviews if today_stat else 0,
        reviewed_today=bool(today_stat and today_stat.reviews),
        streak_current=current,
        streak_longest=longest,
        retention_7d=window_rate(series, 7),
        retention_30d=window_rate(series, 30),
        unaided_rate_30d=window_rate(series, 30, unaided=True),
        average_retrievability=(
            sum(retrievabilities) / len(retrievabilities) if retrievabilities else None
        ),
        curve=series[-curve_days:],
        weak=await briefs_svc.weakest(db, track_slug=track_slug, now=now, limit=5),
    )

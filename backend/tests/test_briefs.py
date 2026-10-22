import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fsrs import Rating

from app.db.models import BriefStatus, PromptKind
from app.services import briefs as svc
from app.services import notes as notes_svc
from app.services import reviews as reviews_svc
from tests.helpers import run_db, seed_note

NOW = datetime(2030, 6, 10, 9, 0, tzinfo=UTC)
UTC_TZ = ZoneInfo("UTC")
Q: list[tuple[str, str, PromptKind]] = [("What is it?", "an answer here", PromptKind.question)]


def reviewed_note(
    title: str,
    *,
    reviewed_at: datetime,
    rating: Rating = Rating.Good,
    tier: int = 0,
    fragile: bool = False,
) -> tuple[uuid.UUID, uuid.UUID]:
    note_id, (item_id,) = seed_note(
        title, f"{title} body text here.", Q, now=reviewed_at - timedelta(minutes=5)
    )

    async def go(db: Any, track: Any) -> None:
        item = await reviews_svc.get_item(db, item_id)
        assert item is not None
        await reviews_svc.grade_item(db, item, rating, hint_tier=tier, now=reviewed_at)
        if fragile:
            item.fragile = True
            await db.commit()

    run_db(go)
    return note_id, item_id


def weakest(limit: int = 3) -> list[Any]:
    async def go(db: Any, track: Any) -> list[Any]:
        return await svc.weakest(db, track_slug="ai-eng", now=NOW, limit=limit)

    return run_db(go)


def build(**kw: Any) -> tuple[Any, bool]:
    async def go(db: Any, track: Any) -> tuple[Any, bool]:
        brief, created = await svc.create_brief(
            db, track_slug="ai-eng", now=kw.pop("now", NOW), tz=kw.pop("tz", UTC_TZ), **kw
        )
        return (brief.id, brief.status, brief.item_ids, brief.due_today, brief.brief_date), created

    return run_db(go)


# ---- picking the weakest notes ----


def test_the_weakest_three_are_forgotten_fragile_and_recently_missed_not_the_fresh_one() -> None:
    forgotten, _ = reviewed_note("Forgotten long ago", reviewed_at=NOW - timedelta(days=80))
    fresh, _ = reviewed_note(
        "Just reviewed", reviewed_at=NOW - timedelta(minutes=2), rating=Rating.Easy
    )
    fragile, _ = reviewed_note("Fragile one", reviewed_at=NOW - timedelta(days=20), fragile=True)
    missed, _ = reviewed_note(
        "Missed yesterday", reviewed_at=NOW - timedelta(hours=20), rating=Rating.Again, tier=3
    )

    picked = weakest(3)
    ids = [w.note_id for w in picked]
    assert fresh not in ids and set(ids) == {forgotten, fragile, missed}
    assert picked == sorted(picked, key=lambda w: -w.score)  # weakest first
    by_note = {w.note_id: w for w in picked}
    assert by_note[fragile].fragile is True and by_note[missed].lapses == 1


def test_a_miss_older_than_a_day_and_a_half_is_not_a_recent_lapse() -> None:
    old_miss, _ = reviewed_note(
        "Old miss", reviewed_at=NOW - timedelta(days=3), rating=Rating.Again, tier=3
    )
    (w,) = weakest(1)
    assert w.note_id == old_miss and w.lapses == 0


def test_each_note_contributes_only_its_weakest_question() -> None:
    note_id, item_a = reviewed_note("Two questions", reviewed_at=NOW - timedelta(days=40))

    async def add_second(db: Any, track: Any) -> uuid.UUID:
        note = await notes_svc.get_note(db, note_id)
        assert note is not None
        second = await reviews_svc.create_item(
            db,
            note,
            kind=PromptKind.question,
            prompt="Another?",
            answer="x y z w",
            now=NOW - timedelta(days=40, minutes=1),
        )
        fresh = await reviews_svc.get_item(db, second.id)
        assert fresh is not None
        await reviews_svc.grade_item(db, fresh, Rating.Easy, now=NOW - timedelta(minutes=1))
        return second.id

    run_db(add_second)
    picked = weakest(5)
    assert len(picked) == 1 and picked[0].item_id == item_a  # the stale one, not the fresh one


def test_unconfirmed_notes_and_never_reviewed_ones_are_not_weak() -> None:
    note_id, _ = reviewed_note("Unconfirmed", reviewed_at=NOW - timedelta(days=60))
    seed_note("Never reviewed", "Body text for a note never reviewed.", Q, now=NOW)

    async def unconfirm(db: Any, track: Any) -> None:
        await notes_svc.update_note(db, (await notes_svc.get_note(db, note_id)), confirmed=False)  # type: ignore[arg-type]

    run_db(unconfirm)
    assert weakest(5) == []


# ---- building the brief ----


def test_a_brief_has_one_question_per_weak_note_and_counts_what_is_due_today() -> None:
    for i, days in enumerate((70, 50, 30)):
        reviewed_note(f"Weak {i}", reviewed_at=NOW - timedelta(days=days))
    reviewed_note("Strong", reviewed_at=NOW - timedelta(minutes=1), rating=Rating.Easy)
    (brief_id, status, item_ids, due_today, brief_date), created = build()
    assert created and status == BriefStatus.ready and len(item_ids) == 3
    assert brief_date == NOW.date() and due_today >= 3


def test_when_few_notes_are_weak_the_brief_is_topped_up_from_what_is_due() -> None:
    reviewed_note("Only weak one", reviewed_at=NOW - timedelta(days=60))
    for i in range(3):
        seed_note(f"Due note {i}", f"Due note {i} body text.", Q, now=NOW - timedelta(hours=i + 1))
    (_, status, item_ids, _, _), _ = build()
    assert status == BriefStatus.ready and len(item_ids) == 3
    assert len(set(item_ids)) == 3


def test_nothing_to_ask_gives_an_empty_brief() -> None:
    (_, status, item_ids, due_today, _), _ = build()
    assert status == BriefStatus.empty and item_ids == [] and due_today == 0


def test_the_cron_can_call_twice_a_day_without_a_second_brief() -> None:
    reviewed_note("Weak", reviewed_at=NOW - timedelta(days=60))
    (first_id, *_), created_first = build()
    (second_id, *_), created_second = build(now=NOW + timedelta(hours=5))
    assert created_first and not created_second and first_id == second_id
    (third_id, *_), created_third = build(now=NOW + timedelta(days=1))  # tomorrow: a new one
    assert created_third and third_id != first_id


def test_force_rebuilds_a_waiting_brief_but_never_one_in_progress() -> None:
    reviewed_note("Weak", reviewed_at=NOW - timedelta(days=60))
    (first_id, *_), _ = build()
    (rebuilt_id, *_), created = build(force=True)
    assert created and rebuilt_id != first_id

    async def start(db: Any, track: Any) -> None:
        brief = await svc.get_brief(db, rebuilt_id)
        assert brief is not None
        await svc.mark_started(db, brief, None)

    run_db(start)
    (kept_id, *_), created = build(force=True)
    assert not created and kept_id == rebuilt_id


def test_a_brief_is_ready_only_today_and_only_until_it_is_started() -> None:
    reviewed_note("Weak", reviewed_at=NOW - timedelta(days=60))
    (brief_id, *_), _ = build()

    async def ready(db: Any, track: Any) -> tuple[Any, Any, Any]:
        today = await svc.ready_brief(db, now=NOW, tz=UTC_TZ)
        tomorrow = await svc.ready_brief(db, now=NOW + timedelta(days=1), tz=UTC_TZ)
        brief = await svc.get_brief(db, brief_id)
        assert brief is not None
        await svc.mark_started(db, brief, None)
        started = await svc.ready_brief(db, now=NOW, tz=UTC_TZ)
        return today and today.id, tomorrow, started

    today_id, tomorrow, started = run_db(ready)
    assert today_id == brief_id and tomorrow is None and started is None


def test_due_today_ends_at_the_users_local_midnight() -> None:
    la = ZoneInfo("America/Los_Angeles")
    now = datetime(2030, 6, 10, 15, 0, tzinfo=UTC)  # 08:00 on the 10th in California
    seed_note(
        "Due this evening", "Due this evening body text.", Q, now=now + timedelta(hours=10)
    )  # 18:00 local
    seed_note(
        "Due after midnight", "Due after midnight body text.", Q, now=now + timedelta(hours=17)
    )  # 01:00 local, the 11th

    async def count(db: Any, track: Any) -> tuple[int, int]:
        return (
            await svc.due_today_count(db, track_slug="ai-eng", now=now, tz=la),
            await svc.due_today_count(db, track_slug="ai-eng", now=now, tz=ZoneInfo("UTC")),
        )

    local, utc = run_db(count)
    assert local == 1  # the 01:00 one belongs to tomorrow in California
    assert utc == 0  # in UTC the day ended at 00:00 on the 11th, before either was due

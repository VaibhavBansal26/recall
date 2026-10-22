import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fsrs import Card, Rating

from app.agent.schemas import ReviewDraft, ReviewDrafts
from app.db.models import PromptKind
from app.services import notes as notes_svc
from app.services import reviews as svc
from tests.helpers import ScriptedLLM, run_db, seed_note

T0 = datetime(2030, 1, 1, 9, 0, tzinfo=UTC)
Q: list[tuple[str, str, PromptKind]] = [
    ("What does RAG do before generating?", "retrieves context", PromptKind.question)
]


def review(item_id: uuid.UUID, rating: Rating, now: datetime, tier: int = 0) -> Any:
    async def go(db: Any, track: Any) -> Any:
        item = await svc.get_item(db, item_id)
        assert item is not None
        outcome = await svc.grade_item(db, item, rating, hint_tier=tier, now=now)
        return outcome.due_at, outcome.fragile, outcome.became_fragile, outcome.cleared_fragile

    return run_db(go)


def due_ids(now: datetime) -> list[uuid.UUID]:
    async def go(db: Any, track: Any) -> list[uuid.UUID]:
        return [i.id for i in await svc.due_items(db, track_slug="ai-eng", now=now)]

    return run_db(go)


# ---- scheduling ----


def test_new_items_are_due_immediately_and_leave_the_queue_once_reviewed() -> None:
    _, (item,) = seed_note("RAG", "RAG retrieves context.", Q, now=T0)
    assert due_ids(T0) == [item]
    due, *_ = review(item, Rating.Good, T0)
    assert due > T0
    assert due_ids(T0 + timedelta(seconds=30)) == []  # not due again right away
    assert due_ids(due + timedelta(minutes=1)) == [item]


def test_after_a_few_days_reviewed_items_come_back_due() -> None:
    """The acceptance check: a day later, due items are what you reviewed, most overdue first."""
    _, (early,) = seed_note("A", "Alpha body text here.", Q, now=T0)
    _, (late,) = seed_note("B", "Beta body text here.", Q, now=T0 + timedelta(hours=5))
    review(early, Rating.Easy, T0)
    review(late, Rating.Easy, T0 + timedelta(hours=5))
    assert due_ids(T0 + timedelta(hours=6)) == []
    assert due_ids(T0 + timedelta(days=60)) == [early, late]


def test_grades_order_the_next_due_date() -> None:
    items = [seed_note(f"N{i}", f"Body number {i} text.", Q, now=T0)[1][0] for i in range(3)]
    again, good, easy = (
        review(i, r, T0)[0]
        for i, r in zip(items, (Rating.Again, Rating.Good, Rating.Easy), strict=True)
    )
    assert again < good < easy


def test_retrievability_is_unknown_until_reviewed_then_decays() -> None:
    _, (item,) = seed_note("R", "Retrievability body text.", Q, now=T0)

    async def go(db: Any, track: Any) -> tuple[Any, Any, Any]:
        fresh = await svc.get_item(db, item)
        assert fresh is not None
        before = svc.retrievability(fresh, T0)
        outcome = await svc.grade_item(db, fresh, Rating.Good, now=T0)
        soon = svc.retrievability(outcome.item, T0 + timedelta(minutes=1))
        later = svc.retrievability(outcome.item, T0 + timedelta(days=90))
        return before, soon, later

    before, soon, later = run_db(go)
    assert before is None
    assert soon is not None and later is not None and soon > 0.95 and later < soon


def test_note_strength_only_counts_reviewed_notes() -> None:
    reviewed, (a,) = seed_note("Reviewed", "Reviewed body text.", Q, now=T0)
    unreviewed, _ = seed_note("Unreviewed", "Untouched body text.", Q, now=T0)
    review(a, Rating.Good, T0)

    async def go(db: Any, track: Any) -> dict[uuid.UUID, float]:
        return await svc.note_strengths(db, track_slug="ai-eng", now=T0 + timedelta(minutes=2))

    strengths = run_db(go)
    assert set(strengths) == {reviewed} and 0 < strengths[reviewed] <= 1
    assert unreviewed not in strengths


# ---- fragile rule: tier 3 twice in a row ----


def test_tier_three_twice_in_a_row_marks_fragile_and_shortens_the_interval() -> None:
    note_id, (item,) = seed_note("Fragile", "Fragile body text here.", Q, now=T0)
    _, f1, became1, _ = review(item, Rating.Again, T0, tier=3)
    assert (f1, became1) == (False, False)  # once is not enough

    t1 = T0 + timedelta(days=1)
    due2, f2, became2, _ = review(item, Rating.Again, t1, tier=3)
    assert (f2, became2) == (True, True)
    assert due2 <= t1 + timedelta(days=1)

    async def note_flag(db: Any, track: Any) -> bool:
        note = await notes_svc.get_note(db, note_id)
        assert note is not None
        return note.fragile

    assert run_db(note_flag) is True


def test_tier_three_with_something_in_between_does_not_count_as_in_a_row() -> None:
    _, (item,) = seed_note("Gap", "Gap body text here.", Q, now=T0)
    review(item, Rating.Again, T0, tier=3)
    review(item, Rating.Hard, T0 + timedelta(days=1), tier=1)
    _, fragile, became, _ = review(item, Rating.Again, T0 + timedelta(days=2), tier=3)
    assert (fragile, became) == (False, False)


def test_a_fragile_item_is_capped_to_a_day_even_when_answered_well() -> None:
    _, (item,) = seed_note("Cap", "Capped body text here.", Q, now=T0)
    when = T0
    for _ in range(4):  # build up a long interval
        due, *_ = review(item, Rating.Easy, when)
        when = due

    async def go(db: Any, track: Any) -> tuple[datetime, datetime]:
        row = await svc.get_item(db, item)
        assert row is not None
        row.fragile = True
        await db.commit()
        uncapped, _ = svc.scheduler.review_card(Card.from_dict(row.fsrs_state), Rating.Good, when)
        outcome = await svc.grade_item(db, row, Rating.Good, hint_tier=1, now=when)
        assert outcome.fragile  # a hinted answer does not clear it
        return uncapped.due, outcome.due_at

    uncapped_due, capped_due = run_db(go)
    assert uncapped_due - when > timedelta(days=1)
    assert capped_due <= when + timedelta(days=1)


def test_two_unaided_correct_answers_in_a_row_clear_fragile() -> None:
    note_id, (item,) = seed_note("Clear", "Clearing body text here.", Q, now=T0)
    review(item, Rating.Again, T0, tier=3)
    review(item, Rating.Again, T0 + timedelta(days=1), tier=3)  # now fragile
    _, still, _, cleared1 = review(item, Rating.Good, T0 + timedelta(days=2))
    assert (still, cleared1) == (True, False)  # previous review was tier 3, so not yet
    _, fragile, _, cleared2 = review(item, Rating.Good, T0 + timedelta(days=3))
    assert (fragile, cleared2) == (False, True)

    async def note_flag(db: Any, track: Any) -> bool:
        note = await notes_svc.get_note(db, note_id)
        assert note is not None
        return note.fragile

    assert run_db(note_flag) is False


# ---- generating items from a note ----


def test_generated_items_are_validated_and_capped() -> None:
    llm = ScriptedLLM(
        ReviewDrafts(
            items=[
                ReviewDraft(kind="cloze", prompt="RAG _____ context first.", answer="retrieves"),
                ReviewDraft(kind="cloze", prompt="_____ and _____ both blank.", answer="x"),
                ReviewDraft(kind="question", prompt="  ", answer="empty prompt"),
                ReviewDraft(
                    kind="question", prompt="What does RAG do?", answer="Retrieves context."
                ),
                ReviewDraft(kind="question", prompt="Extra question?", answer="beyond the cap"),
            ]
        )
    )
    note_id, _ = seed_note("RAG", "RAG retrieves context first.")

    async def go(db: Any, track: Any) -> list[tuple[str, str]]:
        note = await notes_svc.get_note(db, note_id)
        assert note is not None
        created = await svc.generate_items(db, llm, note, max_items=2)
        return [(i.prompt_kind.value, i.prompt) for i in created]

    assert run_db(go) == [("cloze", "RAG _____ context first."), ("question", "What does RAG do?")]


def test_generation_only_ever_asks_the_model_about_the_note() -> None:
    llm = ScriptedLLM(ReviewDrafts(items=[]))
    note_id, _ = seed_note("Embeddings", "Embeddings map text to vectors.")

    async def go(db: Any, track: Any) -> None:
        note = await notes_svc.get_note(db, note_id)
        assert note is not None
        await svc.generate_items(db, llm, note, max_items=2)

    run_db(go)
    assert "Embeddings map text to vectors." in llm.users[0]


def test_async_runner_is_usable_outside_pytest_event_loops() -> None:
    assert asyncio.run(asyncio.sleep(0, "ok")) == "ok"

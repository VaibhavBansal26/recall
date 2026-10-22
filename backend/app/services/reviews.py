"""Spaced repetition with FSRS: review items, grading, fragile handling, due queue."""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from fsrs import Card, Rating, Scheduler
from fsrs.card import CardDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.prompts import load_prompt
from app.agent.schemas import ReviewDraft, ReviewDrafts
from app.db.models import (
    CaptureEvent,
    Note,
    PromptKind,
    ReviewItem,
    ReviewLog,
    Track,
)
from app.llm.client import LLMClient
from app.tracks import guidance_for

log = logging.getLogger(__name__)

# No fuzzing so schedules are reproducible (and testable).
scheduler = Scheduler(enable_fuzzing=False)

# While a note is fragile, its items come back within a day.
FRAGILE_MAX_INTERVAL = timedelta(days=1)


def _now() -> datetime:
    return datetime.now(UTC)


async def get_item(db: AsyncSession, item_id: uuid.UUID) -> ReviewItem | None:
    return (
        await db.execute(select(ReviewItem).where(ReviewItem.id == item_id))
    ).scalar_one_or_none()


async def items_for_note(db: AsyncSession, note_id: uuid.UUID) -> list[ReviewItem]:
    query = select(ReviewItem).where(ReviewItem.note_id == note_id).order_by(ReviewItem.created_at)
    return list((await db.execute(query)).scalars())


async def create_item(
    db: AsyncSession,
    note: Note,
    *,
    kind: PromptKind,
    prompt: str,
    answer: str,
    now: datetime | None = None,
) -> ReviewItem:
    now = now or _now()
    card = Card(due=now)  # a new card is due immediately
    item = ReviewItem(
        note_id=note.id,
        note=note,
        prompt_kind=kind,
        prompt=prompt,
        answer=answer,
        fsrs_state=card.to_dict(),
        due_at=card.due,
    )
    db.add(item)
    await db.commit()
    return item


async def count_session_items(db: AsyncSession, session_id: uuid.UUID) -> int:
    touched = select(CaptureEvent.note_id).where(CaptureEvent.session_id == session_id)
    query = select(func.count()).select_from(ReviewItem).where(ReviewItem.note_id.in_(touched))
    return int((await db.execute(query)).scalar_one())


async def generate_items(
    db: AsyncSession,
    llm: LLMClient,
    note: Note,
    *,
    max_items: int,
    session_id: uuid.UUID | None = None,
) -> list[ReviewItem]:
    """Ask the model for practice prompts drawn only from the note, and store them."""
    drafts = await llm.complete_structured(
        "deep",
        system=load_prompt("review_items").text + guidance_for(note.track.slug, "review"),
        user=f"NOTE TITLE: {note.title}\nNOTE BODY:\n{note.body_md}",
        schema=ReviewDrafts,
        session_id=session_id,
    )
    created: list[ReviewItem] = []
    for draft in filter(_usable, drafts.items):  # validate first, then cap
        if len(created) >= max_items:
            break
        created.append(
            await create_item(
                db,
                note,
                kind=PromptKind(draft.kind),
                prompt=draft.prompt.strip(),
                answer=draft.answer.strip(),
            )
        )
    return created


def _usable(draft: ReviewDraft) -> bool:
    if not draft.prompt.strip() or not draft.answer.strip():
        return False
    return draft.kind != "cloze" or draft.prompt.count("_____") == 1


async def due_items(
    db: AsyncSession,
    *,
    track_slug: str | None = None,
    note_ids: list[uuid.UUID] | None = None,
    now: datetime | None = None,
    limit: int = 20,
    include_not_due: bool = False,
) -> list[ReviewItem]:
    """Items to ask next, most overdue first. Questions come from what is due, not at random."""
    now = now or _now()
    query = (
        select(ReviewItem)
        .join(Note, Note.id == ReviewItem.note_id)
        .where(Note.confirmed.is_(True))  # unapproved source/assistant notes are not quizzed
    )
    if track_slug:
        query = query.join(Track, Track.id == Note.track_id).where(Track.slug == track_slug)
    if note_ids is not None:
        query = query.where(ReviewItem.note_id.in_(note_ids))
    if not include_not_due:
        query = query.where(ReviewItem.due_at <= now)
    query = query.order_by(ReviewItem.due_at).limit(limit)
    return list((await db.execute(query)).scalars())


async def count_due(
    db: AsyncSession, *, track_slug: str | None = None, now: datetime | None = None
) -> int:
    now = now or _now()
    query = (
        select(func.count())
        .select_from(ReviewItem)
        .join(Note, Note.id == ReviewItem.note_id)
        .where(ReviewItem.due_at <= now, Note.confirmed.is_(True))
    )
    if track_slug:
        query = query.join(Track, Track.id == Note.track_id).where(Track.slug == track_slug)
    return int((await db.execute(query)).scalar_one())


async def next_due_at(
    db: AsyncSession, *, track_slug: str | None = None, now: datetime | None = None
) -> datetime | None:
    now = now or _now()
    query = (
        select(func.min(ReviewItem.due_at))
        .select_from(ReviewItem)
        .join(Note, Note.id == ReviewItem.note_id)
        .where(ReviewItem.due_at > now, Note.confirmed.is_(True))
    )
    if track_slug:
        query = query.join(Track, Track.id == Note.track_id).where(Track.slug == track_slug)
    return (await db.execute(query)).scalar_one_or_none()


def retrievability(item: ReviewItem, now: datetime | None = None) -> float | None:
    """Probability (0..1) the learner can still recall the item; None if never reviewed."""
    if item.last_reviewed_at is None:
        return None
    return float(
        scheduler.get_card_retrievability(
            Card.from_dict(cast(CardDict, item.fsrs_state)), now or _now()
        )
    )


async def note_strengths(
    db: AsyncSession, *, track_slug: str | None = None, now: datetime | None = None
) -> dict[uuid.UUID, float]:
    """Mean retrievability per note across its reviewed items (for the memory map colours)."""
    query = select(ReviewItem).join(Note, Note.id == ReviewItem.note_id)
    if track_slug:
        query = query.join(Track, Track.id == Note.track_id).where(Track.slug == track_slug)
    by_note: dict[uuid.UUID, list[float]] = {}
    for item in (await db.execute(query)).scalars():
        r = retrievability(item, now)
        if r is not None:
            by_note.setdefault(item.note_id, []).append(r)
    return {n: sum(v) / len(v) for n, v in by_note.items()}


@dataclass(frozen=True)
class GradeOutcome:
    item: ReviewItem
    rating: Rating
    fragile: bool
    became_fragile: bool
    cleared_fragile: bool
    due_at: datetime


async def _previous_log(db: AsyncSession, item_id: uuid.UUID) -> ReviewLog | None:
    query = (
        select(ReviewLog)
        .where(ReviewLog.review_item_id == item_id)
        .order_by(ReviewLog.reviewed_at.desc())
        .limit(1)
    )
    return (await db.execute(query)).scalar_one_or_none()


async def grade_item(
    db: AsyncSession,
    item: ReviewItem,
    rating: Rating,
    *,
    hint_tier: int = 0,
    latency_ms: int | None = None,
    session_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> GradeOutcome:
    """Apply an FSRS review, log it, and update the fragile flags.

    Needing the full reveal (tier 3) twice in a row marks the item and its note fragile and
    pulls the next review in to within a day. Two unaided correct answers in a row clear it.
    """
    now = now or _now()
    previous = await _previous_log(db, item.id)

    card, _ = scheduler.review_card(Card.from_dict(cast(CardDict, item.fsrs_state)), rating, now)

    became = cleared = False
    if hint_tier == 3 and previous is not None and previous.hint_tier_used == 3:
        became = not item.fragile
        item.fragile = True
    elif (
        item.fragile
        and hint_tier == 0
        and rating >= Rating.Good
        and previous is not None
        and previous.hint_tier_used == 0
        and previous.grade >= Rating.Good
    ):
        item.fragile = False
        cleared = True

    if item.fragile and card.due - now > FRAGILE_MAX_INTERVAL:
        card.due = now + FRAGILE_MAX_INTERVAL

    item.fsrs_state = dict(card.to_dict())
    item.due_at = card.due
    item.last_reviewed_at = now
    db.add(
        ReviewLog(
            review_item_id=item.id,
            reviewed_at=now,
            grade=int(rating),
            hint_tier_used=hint_tier,
            latency_ms=latency_ms,
            session_id=session_id,
        )
    )

    note = item.note
    if became:
        note.fragile = True
    if cleared:
        others = await db.execute(
            select(func.count())
            .select_from(ReviewItem)
            .where(
                ReviewItem.note_id == note.id,
                ReviewItem.id != item.id,
                ReviewItem.fragile.is_(True),
            )
        )
        if others.scalar_one() == 0:
            note.fragile = False
    await db.commit()
    return GradeOutcome(item, rating, item.fragile, became, cleared, item.due_at)

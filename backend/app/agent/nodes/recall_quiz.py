"""recall_quiz: ask what is due, run the hint ladder, grade with FSRS."""

import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fsrs import Rating

from app.agent.deps import AgentDeps
from app.agent.hint_ladder import MAX_TIER, HintLadder, Step, rating_for
from app.agent.prompts import load_prompt
from app.agent.schemas import QuizTurn
from app.db.models import PromptKind, ReviewItem
from app.services import reviews as reviews_svc
from app.voice.events import QuizStateEvent, QuizSummary

_NO_ANSWER = re.compile(
    r"^\s*(i forgot|forgot|i don'?t (know|remember)|no idea|not sure|pass|blank|hmm+|um+)\W*$", re.I
)


@dataclass
class QuizStep:
    spoken: str
    events: list[QuizStateEvent]
    diagram_note_id: uuid.UUID | None = None  # show/build this note's diagram (tier 3 reveal)
    ended: bool = False


@dataclass
class _Result:
    tier: int
    fragile: bool


@dataclass
class QuizSession:
    deps: AgentDeps
    session_id: uuid.UUID
    track: str
    queue: list[uuid.UUID] = field(default_factory=list)
    current: uuid.UUID | None = None
    ladder: HintLadder = field(default_factory=HintLadder)
    asked_at: float = 0.0
    position: int = 0
    total: int = 0
    results: list[_Result] = field(default_factory=list)

    # ---------------------------------------------------------------- start / ask

    async def start(
        self,
        *,
        note_id: uuid.UUID | None = None,
        note_ids: list[uuid.UUID] | None = None,
        items: list[ReviewItem] | None = None,
    ) -> QuizStep:
        async with self.deps.sessionmaker() as db:
            if items is None:
                if note_id is not None:  # practice on one note, due or not
                    items = await reviews_svc.items_for_note(db, note_id)
                else:
                    items = await reviews_svc.due_items(
                        db,
                        track_slug=self.track,
                        note_ids=note_ids,
                        limit=self.deps.settings.quiz_batch,
                    )
            if not items:
                next_due = await reviews_svc.next_due_at(db, track_slug=self.track)
                return _empty(next_due)
        batch = items[: self.deps.settings.quiz_batch]
        self.queue = [i.id for i in batch]
        self.total = len(batch)
        return await self._ask_next(lead="Okay, let's practise. " if note_id else "Okay. ")

    async def _ask_next(self, lead: str = "") -> QuizStep:
        if not self.queue:
            return self._summary()
        item_id = self.queue.pop(0)
        async with self.deps.sessionmaker() as db:
            item = await reviews_svc.get_item(db, item_id)
        if item is None:
            return await self._ask_next(lead)
        self.current = item.id
        self.ladder = HintLadder()
        self.position += 1
        self.asked_at = time.perf_counter()
        event = QuizStateEvent(
            phase="asking",
            item_id=item.id,
            note_id=item.note_id,
            note_title=item.note.title,
            prompt=item.prompt,
            position=self.position,
            total=self.total,
        )
        return QuizStep(lead + _speakable_prompt(item), [event])

    # ---------------------------------------------------------------- answering

    async def answer(self, text: str) -> QuizStep:
        item = await self._current_item()
        if item is None:
            return await self._ask_next()
        if _NO_ANSWER.match(text):
            return await self.hint()
        if self.ladder.tier >= MAX_TIER:  # the follow-up after a full reveal ends the question
            return await self._finish(item, self.ladder.on_give_up())
        turn = await self._turn(item, text, min(self.ladder.tier + 1, MAX_TIER))
        step = self.ladder.on_answer(turn.correct)
        return await self._after_step(item, step, turn.spoken_hint)

    async def hint(self) -> QuizStep:
        """The learner forgot or asked for a hint: climb the ladder."""
        item = await self._current_item()
        if item is None:
            return await self._ask_next()
        step = self.ladder.on_give_up()
        if step.action == "finish":
            return await self._finish(item, step)
        turn = await self._turn(item, "", step.tier)
        return await self._after_step(item, step, turn.spoken_hint)

    async def skip(self) -> QuizStep:
        """Move on without grading (the item stays due)."""
        return await self._ask_next(lead="Okay, skipping. ")

    async def end(self) -> QuizStep:
        return self._summary(lead="Okay, stopping the quiz. ")

    async def _after_step(self, item: ReviewItem, step: Step, spoken_hint: str) -> QuizStep:
        if step.action == "finish":
            return await self._finish(item, step)
        reveal = step.tier >= MAX_TIER
        spoken = spoken_hint.strip() or _default_hint(item, step.tier)
        event = QuizStateEvent(
            phase="hint",
            item_id=item.id,
            note_id=item.note_id,
            note_title=item.note.title,
            prompt=item.prompt,
            tier=step.tier,
            hint=spoken,
            answer=item.answer if reveal else None,
            position=self.position,
            total=self.total,
        )
        return QuizStep(spoken, [event], diagram_note_id=item.note_id if reveal else None)

    async def _finish(self, item: ReviewItem, step: Step) -> QuizStep:
        tier = step.tier
        latency_ms = int((time.perf_counter() - self.asked_at) * 1000)
        rating = rating_for(tier, latency_ms if tier == 0 else None)
        async with self.deps.sessionmaker() as db:
            fresh = await reviews_svc.get_item(db, item.id)
            assert fresh is not None
            outcome = await reviews_svc.grade_item(
                db,
                fresh,
                rating,
                hint_tier=tier,
                latency_ms=latency_ms,
                session_id=self.session_id,
            )
        self.results.append(_Result(tier, outcome.fragile))

        spoken = _feedback(tier, outcome.became_fragile)
        graded = QuizStateEvent(
            phase="graded",
            item_id=item.id,
            note_id=item.note_id,
            note_title=item.note.title,
            prompt=item.prompt,
            tier=tier,
            answer=item.answer,
            grade=Rating(rating).name,
            fragile=outcome.fragile,
            next_due=outcome.due_at,
            position=self.position,
            total=self.total,
        )
        self.current = None
        if not self.queue:
            summary = self._summary(lead=spoken + " ")
            return QuizStep(summary.spoken, [graded, *summary.events], ended=True)
        nxt = await self._ask_next(lead=spoken + " Next question. ")
        return QuizStep(nxt.spoken, [graded, *nxt.events])

    # ---------------------------------------------------------------- helpers

    async def _current_item(self) -> ReviewItem | None:
        if self.current is None:
            return None
        async with self.deps.sessionmaker() as db:
            return await reviews_svc.get_item(db, self.current)

    async def _turn(self, item: ReviewItem, answer: str, tier: int) -> QuizTurn:
        """One fast-model call that grades the answer and writes the next hint."""
        user = (
            f"QUESTION: {item.prompt}\n"
            f"EXPECTED ANSWER: {item.answer}\n"
            f"NOTE TITLE: {item.note.title}\n"
            f"NOTE BODY: {item.note.body_md}\n"
            f"ANSWER: {answer}\n"
            f"HINT TIER: {tier}"
        )
        return await self.deps.llm.complete_structured(
            "fast",
            system=load_prompt("quiz_turn").text,
            user=user,
            schema=QuizTurn,
            session_id=self.session_id,
        )

    def _summary(self, lead: str = "") -> QuizStep:
        results = self.results
        summary = QuizSummary(
            total=len(results),
            unaided=sum(1 for r in results if r.tier == 0),
            hinted=sum(1 for r in results if r.tier in (1, 2)),
            revealed=sum(1 for r in results if r.tier == MAX_TIER),
            fragile=sum(1 for r in results if r.fragile),
        )
        if not results:
            spoken = lead + "We didn't get to any questions."
        else:
            spoken = lead + (
                f"That's it for now. You answered {summary.unaided} of {summary.total} "
                "without a hint."
            )
        event = QuizStateEvent(phase="ended", summary=summary)
        return QuizStep(spoken, [event], ended=True)


def _speakable_prompt(item: ReviewItem) -> str:
    text = item.prompt.replace("_____", "blank")
    return f"Fill in the blank. {text}" if item.prompt_kind == PromptKind.cloze else text


def _default_hint(item: ReviewItem, tier: int) -> str:
    if tier <= 1:
        return f"Here's a nudge: think about {item.note.title}."
    if tier == 2:
        return "It starts like this: " + " ".join(item.answer.split()[:3]) + "."
    return f"The answer is {item.answer}. Can you say that back in your own words?"


def _feedback(tier: int, became_fragile: bool) -> str:
    base = {
        0: "That's right.",
        1: "Good, you got there with a nudge.",
        2: "Okay, we'll come back to that one soon.",
        3: "No problem, we'll revisit that one.",
    }[tier]
    return base + (" I'll bring this one back sooner." if became_fragile else "")


def _empty(next_due: datetime | None) -> QuizStep:
    if next_due is None:
        spoken = "There's nothing to review yet. Tell me some ideas first and I'll quiz you later."
    else:
        mins = max(1, int((next_due - datetime.now(UTC)).total_seconds() // 60))
        when = f"{mins} minutes" if mins < 90 else f"about {round(mins / 60)} hours"
        if mins >= 36 * 60:
            when = f"about {round(mins / 1440)} days"
        spoken = f"Nothing is due right now. Your next review is in {when}."
    return QuizStep(spoken, [QuizStateEvent(phase="empty", next_due=next_due)], ended=True)


__all__ = ["QuizSession", "QuizStep"]

"""Read-back: read the learner's notes aloud in learning order, one at a time, with a question."""

import uuid
from dataclasses import dataclass, field

from app.agent.deps import AgentDeps
from app.agent.prompts import load_prompt
from app.agent.schemas import WhyMatters
from app.db.models import Note, ReviewItem
from app.services import notes as notes_svc
from app.services import retrieval
from app.services import reviews as reviews_svc
from app.voice.events import ReadBackEvent

MIN_SPEED, MAX_SPEED, SPEED_STEP = 0.7, 1.2, 0.15


@dataclass
class ReadBackStep:
    spoken: str
    events: list[ReadBackEvent]
    note_id: uuid.UUID | None = None  # note whose diagram to show
    finished: bool = False
    question_item: ReviewItem | None = None  # hand over to the quiz for this question


@dataclass
class ReadBackSession:
    topic: str | None
    note_ids: list[uuid.UUID]
    index: int = 0
    speed: float = 1.0
    _titles: dict[uuid.UUID, str] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.note_ids)


async def start(
    deps: AgentDeps, track: str, topic: str | None, limit: int = 6
) -> ReadBackSession | None:
    async with deps.sessionmaker() as db:
        if topic:
            found = await retrieval.hybrid_search(
                db, deps.embedder, track_slug=track, query=topic, limit=limit
            )
        else:
            found = (await notes_svc.list_notes(db, track, limit=limit))[::-1]
        ordered = await retrieval.order_by_prerequisites(db, found)
    if not ordered:
        return None
    return ReadBackSession(topic=topic, note_ids=[n.id for n in ordered])


async def _why(deps: AgentDeps, note: Note, session_id: uuid.UUID) -> str:
    result = await deps.llm.complete_structured(
        "fast",
        system=load_prompt("why_matters").text,
        user=f"NOTE: {note.title}. {note.body_md}",
        schema=WhyMatters,
        session_id=session_id,
    )
    return result.line


async def read_current(deps: AgentDeps, rb: ReadBackSession, session_id: uuid.UUID) -> ReadBackStep:
    async with deps.sessionmaker() as db:
        note = await notes_svc.get_note(db, rb.note_ids[rb.index])
        if note is None:  # deleted meanwhile
            return await advance(deps, rb, session_id)
        items = await reviews_svc.items_for_note(db, note.id)
    why = await _why(deps, note, session_id)
    last = rb.index == rb.total - 1
    spoken = f"Note {rb.index + 1} of {rb.total}. {note.title}. {note.body_md} {why}"

    question_item = None
    if last:
        if items:
            question_item = items[0]
            spoken += " That's the last one. Here's a question to finish."
        else:
            spoken += (
                f" That's the last one. In your own words, what's the main idea of {note.title}?"
            )
    else:
        spoken += " Say next to continue, repeat to hear it again, or stop."

    event = ReadBackEvent(
        index=rb.index,
        total=rb.total,
        note_id=note.id,
        title=note.title,
        body_md=note.body_md,
        why=why,
        speed=rb.speed,
        finished=last,
    )
    return ReadBackStep(
        spoken, [event], note_id=note.id, finished=last, question_item=question_item
    )


async def advance(deps: AgentDeps, rb: ReadBackSession, session_id: uuid.UUID) -> ReadBackStep:
    if rb.index + 1 >= rb.total:
        return stop(rb, "That's all of them.")
    rb.index += 1
    return await read_current(deps, rb, session_id)


def stop(rb: ReadBackSession, spoken: str = "Okay, stopping there.") -> ReadBackStep:
    event = ReadBackEvent(index=rb.index, total=rb.total, speed=rb.speed, finished=True)
    return ReadBackStep(spoken, [event], finished=True)


def change_speed(rb: ReadBackSession, command: str) -> None:
    delta = -SPEED_STEP if command == "slower" else SPEED_STEP
    rb.speed = round(min(MAX_SPEED, max(MIN_SPEED, rb.speed + delta)), 2)

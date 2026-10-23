"""Read-back: read the learner's notes aloud in learning order, one at a time, with a question."""

import uuid
from dataclasses import dataclass, field

from app.agent.deps import AgentDeps
from app.agent.prompts import load_prompt
from app.agent.schemas import ReciteExplain, WhyMatters
from app.db.models import Note, ReviewItem
from app.services import notebooks as notebooks_svc
from app.services import notes as notes_svc
from app.services import retrieval
from app.services import reviews as reviews_svc
from app.tracks import guidance_for
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
    # Recite: explain each note, then ask one question about it before moving on.
    check: bool = False
    notebook_name: str | None = None
    _titles: dict[uuid.UUID, str] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.note_ids)


async def start(
    deps: AgentDeps,
    track: str,
    topic: str | None,
    limit: int = 6,
    *,
    notebook_id: uuid.UUID | None = None,
    check: bool = False,
) -> ReadBackSession | None:
    """Notes to read: a whole notebook (in the order they were made), else a topic search, else the
    latest notes."""
    async with deps.sessionmaker() as db:
        notebook_name = None
        if notebook_id is not None:
            book = await notebooks_svc.get_notebook(db, notebook_id)
            notebook_name = book.name if book else None
            ordered = await notebooks_svc.notes_in(db, notebook_id)
        else:
            if topic:
                found = await retrieval.hybrid_search(
                    db, deps.embedder, track_slug=track, query=topic, limit=limit
                )
            else:
                found = (await notes_svc.list_notes(db, track, limit=limit))[::-1]
            ordered = await retrieval.order_by_prerequisites(db, found)
    if not ordered:
        return None
    return ReadBackSession(
        topic=topic,
        note_ids=[n.id for n in ordered],
        check=check,
        notebook_name=notebook_name,
    )


async def _why(deps: AgentDeps, note: Note, session_id: uuid.UUID) -> str:
    result = await deps.llm.complete_structured(
        "fast",
        system=load_prompt("why_matters").text,
        user=f"NOTE: {note.title}. {note.body_md}",
        schema=WhyMatters,
        session_id=session_id,
    )
    return result.line


async def _explain(deps: AgentDeps, note: Note, session_id: uuid.UUID) -> str:
    result = await deps.llm.complete_structured(
        "fast",
        system=load_prompt("recite_explain").text + guidance_for(note.track.slug, "explain"),
        user=f"NOTE: {note.title}. {note.body_md}",
        schema=ReciteExplain,
        session_id=session_id,
    )
    return result.text


async def _question_for(deps: AgentDeps, note: Note, session_id: uuid.UUID) -> ReviewItem | None:
    """A question to check recall of this note; one is written on the spot if it has none."""
    async with deps.sessionmaker() as db:
        items = await reviews_svc.items_for_note(db, note.id)
        if items:
            return items[0]
        made = await reviews_svc.generate_items(
            db, deps.llm, note, max_items=1, session_id=session_id
        )
        return made[0] if made else None


async def read_current(deps: AgentDeps, rb: ReadBackSession, session_id: uuid.UUID) -> ReadBackStep:
    async with deps.sessionmaker() as db:
        note = await notes_svc.get_note(db, rb.note_ids[rb.index])
        if note is None:  # deleted meanwhile
            return await advance(deps, rb, session_id)
        items = await reviews_svc.items_for_note(db, note.id)
    last = rb.index == rb.total - 1
    if rb.check:
        explanation = await _explain(deps, note, session_id)
        question = await _question_for(deps, note, session_id)
        spoken = f"Note {rb.index + 1} of {rb.total}. {note.title}. {note.body_md} {explanation}"
        spoken += " Let me check that. " if question else " "
        event = ReadBackEvent(
            index=rb.index,
            total=rb.total,
            note_id=note.id,
            title=note.title,
            body_md=note.body_md,
            why=explanation,
            speed=rb.speed,
            finished=last,
        )
        return ReadBackStep(
            spoken.rstrip() + " " if question is None else spoken,
            [event],
            note_id=note.id,
            finished=last,
            question_item=question,
        )
    why = await _why(deps, note, session_id)
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

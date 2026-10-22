"""Capture: turn what the user said into atomic notes, merging instead of duplicating."""

import logging
from collections.abc import AsyncIterator

from app.agent.deps import AgentDeps
from app.agent.prompts import load_prompt
from app.agent.schemas import ExtractedNotes, MergeResult
from app.agent.state import AgentState, CaptureItem
from app.db.models import CaptureAction, CaptureEvent, Note, NoteOrigin
from app.services import notes as notes_svc
from app.services.sessions import get_track

log = logging.getLogger(__name__)


def ack_stream(deps: AgentDeps, state: AgentState) -> AsyncIterator[str]:
    """The spoken side of a capture turn: a brief acknowledgement, never an interruption."""
    return deps.llm.stream_text(
        "fast",
        system=load_prompt("capture_ack").text,
        user=state.user_text,
        session_id=state.session_id,
    )


def _item(event: CaptureEvent, note: Note) -> CaptureItem:
    before = event.before or {}
    return CaptureItem(
        event_id=event.id,
        action=event.action.value,
        similarity=event.similarity,
        note_id=note.id,
        title=note.title,
        body_md=note.body_md,
        origin=note.origin.value,
        confirmed=note.confirmed,
        before_title=before.get("title"),
        before_body_md=before.get("body_md"),
    )


async def capture_node(deps: AgentDeps, state: AgentState) -> AgentState:
    extract_prompt = load_prompt("capture_extract")
    merge_prompt = load_prompt("capture_merge")

    async with deps.sessionmaker() as db:
        track = await get_track(db, state.track)
        if track is None:
            raise ValueError(f"Unknown track {state.track!r}")

        system = extract_prompt.text.format(
            track_name=track.name, track_description=track.config.get("description", "")
        )
        context = "\n".join(state.transcript_window) or "(none)"
        extracted = await deps.llm.complete_structured(
            "deep",
            system=system,
            user=f"CONTEXT:\n{context}\n\nLATEST:\n{state.user_text}",
            schema=ExtractedNotes,
            session_id=state.session_id,
        )
        candidates = extracted.notes[: deps.settings.max_notes_per_turn]
        if not candidates:
            return state

        embeddings = await deps.embedder.embed([f"{c.title}\n{c.body_md}" for c in candidates])

        items: list[CaptureItem] = []
        for cand, embedding in zip(candidates, embeddings, strict=True):
            dup = await notes_svc.find_duplicate(
                db, track.id, cand.title, embedding, deps.settings.dedup_similarity
            )
            if dup is None:
                note, event = await notes_svc.create_note(
                    db,
                    track=track,
                    title=cand.title,
                    body_md=cand.body_md,
                    origin=NoteOrigin.user,
                    embedding=embedding,
                    session_id=state.session_id,
                )
                assert event is not None and event.action == CaptureAction.created
            else:
                existing, similarity = dup
                merged = await deps.llm.complete_structured(
                    "deep",
                    system=merge_prompt.text,
                    user=f"EXISTING:\n{existing.body_md}\nNEW:\n{cand.body_md}",
                    schema=MergeResult,
                    session_id=state.session_id,
                )
                event = await notes_svc.merge_into(
                    db,
                    note=existing,
                    body_md=merged.body_md,
                    embedding=embedding,
                    similarity=similarity,
                    session_id=state.session_id,
                )
                note = existing
            items.append(_item(event, note))

    log.info("capture: %d note(s) from %r", len(items), state.user_text[:60])
    return state.model_copy(update={"captured": items})

import uuid

from fastapi import APIRouter, HTTPException, Request

from app.api.deps import Db
from app.db.models import Note, NoteOrigin
from app.schemas import DiagramOut, NoteCreate, NoteOut, NotePatch, UndoOut
from app.services import diagrams as diagram_svc
from app.services import notes as svc
from app.services.sessions import get_track

router = APIRouter(prefix="/api")


def to_note_out(note: Note) -> NoteOut:
    return NoteOut(
        id=note.id,
        track=note.track.slug,
        title=note.title,
        body_md=note.body_md,
        origin=note.origin,
        confirmed=note.confirmed,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


async def _embed(request: Request, title: str, body_md: str) -> list[float]:
    vectors: list[list[float]] = await request.app.state.deps.embedder.embed(
        [f"{title}\n{body_md}"]
    )
    return vectors[0]


@router.get("/notes", response_model=list[NoteOut])
async def list_notes(db: Db, track: str | None = None) -> list[NoteOut]:
    return [to_note_out(n) for n in await svc.list_notes(db, track)]


@router.post("/notes", response_model=NoteOut, status_code=201)
async def create_note(body: NoteCreate, db: Db, request: Request) -> NoteOut:
    track = await get_track(db, body.track)
    if track is None:
        raise HTTPException(status_code=404, detail=f"Unknown track {body.track!r}")
    embedding = await _embed(request, body.title, body.body_md)
    note, _ = await svc.create_note(
        db,
        track=track,
        title=body.title,
        body_md=body.body_md,
        origin=NoteOrigin.user,
        embedding=embedding,
        record_event=False,
    )
    return to_note_out(note)


@router.get("/notes/{note_id}", response_model=NoteOut)
async def get_note(note_id: uuid.UUID, db: Db) -> NoteOut:
    note = await svc.get_note(db, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return to_note_out(note)


@router.patch("/notes/{note_id}", response_model=NoteOut)
async def patch_note(note_id: uuid.UUID, body: NotePatch, db: Db, request: Request) -> NoteOut:
    note = await svc.get_note(db, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    title = body.title if body.title is not None else note.title
    body_md = body.body_md if body.body_md is not None else note.body_md
    changed = body.title is not None or body.body_md is not None
    embedding = await _embed(request, title, body_md) if changed else None
    note = await svc.update_note(
        db,
        note,
        title=body.title,
        body_md=body.body_md,
        confirmed=body.confirmed,
        embedding=embedding,
    )
    return to_note_out(note)


@router.post("/capture-events/{event_id}/undo", response_model=UndoOut)
async def undo_capture(event_id: uuid.UUID, db: Db) -> UndoOut:
    event = await svc.undo_capture(db, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Capture event not found")
    return UndoOut(event_id=event.id, action=event.action.value, undone=event.undone)


@router.get("/notes/{note_id}/diagram", response_model=DiagramOut)
async def get_diagram(note_id: uuid.UUID, db: Db) -> DiagramOut:
    diagram = await diagram_svc.get_diagram(db, note_id)
    if diagram is None:
        raise HTTPException(status_code=404, detail="No diagram for this note")
    return DiagramOut(
        note_id=diagram.note_id,
        kind=diagram.kind,
        source=diagram.source,
        created_at=diagram.created_at,
    )


@router.post("/notes/{note_id}/diagram/regenerate", response_model=DiagramOut)
async def regenerate_diagram(note_id: uuid.UUID, db: Db, request: Request) -> DiagramOut:
    note = await svc.get_note(db, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    kind, source = await diagram_svc.build_diagram(
        request.app.state.deps.llm, title=note.title, body_md=note.body_md
    )
    diagram = await diagram_svc.save_diagram(db, note.id, kind, source)
    return DiagramOut(
        note_id=diagram.note_id,
        kind=diagram.kind,
        source=diagram.source,
        created_at=diagram.created_at,
    )

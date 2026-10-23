import uuid

from fastapi import APIRouter, HTTPException

from app.api.deps import Db
from app.api.notes import to_note_out
from app.db.models import Notebook
from app.schemas import NotebookCreate, NotebookOut, NotebookPatch, NoteOut
from app.services import notebooks as svc
from app.services.sessions import get_track

router = APIRouter(prefix="/api")


def to_notebook_out(book: Notebook, note_count: int) -> NotebookOut:
    return NotebookOut(
        id=book.id,
        track=book.track.slug,
        name=book.name,
        kind=book.kind,
        note_count=note_count,
        source_id=book.source_id,
        created_at=book.created_at,
        updated_at=book.updated_at,
    )


async def _get(db: Db, notebook_id: uuid.UUID) -> Notebook:
    book = await svc.get_notebook(db, notebook_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Notebook not found")
    return book


@router.get("/notebooks", response_model=list[NotebookOut])
async def list_notebooks(db: Db, track: str | None = None) -> list[NotebookOut]:
    return [to_notebook_out(b, n) for b, n in await svc.list_with_counts(db, track)]


@router.post("/notebooks", response_model=NotebookOut, status_code=201)
async def create_notebook(body: NotebookCreate, db: Db) -> NotebookOut:
    track = await get_track(db, body.track)
    if track is None:
        raise HTTPException(status_code=404, detail=f"Unknown track {body.track!r}")
    try:
        book, _ = await svc.get_or_create(db, track, body.name, body.kind)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    return to_notebook_out(book, await svc.count_notes(db, book.id))


@router.get("/notebooks/{notebook_id}/notes", response_model=list[NoteOut])
async def notebook_notes(notebook_id: uuid.UUID, db: Db) -> list[NoteOut]:
    await _get(db, notebook_id)
    return [to_note_out(n) for n in await svc.notes_in(db, notebook_id)]


@router.patch("/notebooks/{notebook_id}", response_model=NotebookOut)
async def rename_notebook(notebook_id: uuid.UUID, body: NotebookPatch, db: Db) -> NotebookOut:
    book = await _get(db, notebook_id)
    try:
        await svc.rename(db, book, body.name)
    except ValueError as err:
        raise HTTPException(status_code=409, detail=str(err)) from err
    return to_notebook_out(book, await svc.count_notes(db, book.id))


@router.delete("/notebooks/{notebook_id}", status_code=204)
async def delete_notebook(notebook_id: uuid.UUID, db: Db) -> None:
    """Delete the notebook only; its notes stay, unfiled."""
    await svc.delete(db, await _get(db, notebook_id))

import uuid

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy.exc import IntegrityError

from app.api.deps import Db
from app.db.models import NoteLink, NoteOrigin
from app.schemas import LinkCreate, LinkOut, LinkPatch
from app.services import links as svc
from app.services import notes as notes_svc

router = APIRouter(prefix="/api")


def to_link_out(link: NoteLink) -> LinkOut:
    return LinkOut(
        id=link.id,
        from_note_id=link.from_note_id,
        to_note_id=link.to_note_id,
        from_title=link.from_note.title,
        to_title=link.to_note.title,
        kind=link.kind,
        origin=link.origin,
        confirmed=link.confirmed,
    )


@router.get("/notes/{note_id}/links", response_model=list[LinkOut])
async def note_links(note_id: uuid.UUID, db: Db) -> list[LinkOut]:
    if await notes_svc.get_note(db, note_id) is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return [to_link_out(link) for link in await svc.links_for_note(db, note_id)]


@router.post("/links", response_model=LinkOut, status_code=201)
async def create_link(body: LinkCreate, db: Db) -> LinkOut:
    if body.from_note_id == body.to_note_id:
        raise HTTPException(status_code=422, detail="A note cannot link to itself")
    for note_id in (body.from_note_id, body.to_note_id):
        if await notes_svc.get_note(db, note_id) is None:
            raise HTTPException(status_code=404, detail="Note not found")
    if await svc.pair_is_linked(db, body.from_note_id, body.to_note_id):
        raise HTTPException(status_code=409, detail="These notes are already linked")
    try:
        link = await svc.create_link(
            db,
            from_note_id=body.from_note_id,
            to_note_id=body.to_note_id,
            kind=body.kind,
            origin=NoteOrigin.user,
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="These notes are already linked") from exc
    return to_link_out(link)


@router.patch("/links/{link_id}", response_model=LinkOut)
async def patch_link(link_id: uuid.UUID, body: LinkPatch, db: Db) -> LinkOut:
    link = await svc.get_link(db, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Link not found")
    link.confirmed = body.confirmed
    await db.commit()
    return to_link_out(link)


@router.delete("/links/{link_id}", status_code=204)
async def delete_link(link_id: uuid.UUID, db: Db) -> Response:
    link = await svc.get_link(db, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Link not found")
    await db.delete(link)
    await db.commit()
    return Response(status_code=204)

import logging
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.prompts import load_prompt
from app.agent.schemas import LinkProposals
from app.config import Settings
from app.db.models import LinkKind, Note, NoteLink, NoteOrigin, Track
from app.llm.client import LLMClient

log = logging.getLogger(__name__)


async def get_link(db: AsyncSession, link_id: uuid.UUID) -> NoteLink | None:
    return (await db.execute(select(NoteLink).where(NoteLink.id == link_id))).scalar_one_or_none()


async def links_for_note(db: AsyncSession, note_id: uuid.UUID) -> list[NoteLink]:
    query = (
        select(NoteLink)
        .where(or_(NoteLink.from_note_id == note_id, NoteLink.to_note_id == note_id))
        .order_by(NoteLink.created_at)
    )
    return list((await db.execute(query)).scalars())


async def links_for_track(db: AsyncSession, track_slug: str | None) -> list[NoteLink]:
    query = select(NoteLink).order_by(NoteLink.created_at)
    if track_slug:
        query = query.join(Note, Note.id == NoteLink.from_note_id).join(
            Track, Track.id == Note.track_id
        )
        query = query.where(Track.slug == track_slug)
    return list((await db.execute(query)).scalars())


async def pair_is_linked(db: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> bool:
    query = select(NoteLink.id).where(
        or_(
            (NoteLink.from_note_id == a) & (NoteLink.to_note_id == b),
            (NoteLink.from_note_id == b) & (NoteLink.to_note_id == a),
        )
    )
    return (await db.execute(query.limit(1))).first() is not None


async def create_link(
    db: AsyncSession,
    *,
    from_note_id: uuid.UUID,
    to_note_id: uuid.UUID,
    kind: LinkKind,
    origin: NoteOrigin,
) -> NoteLink:
    link = NoteLink(
        from_note_id=from_note_id,
        to_note_id=to_note_id,
        kind=kind,
        origin=origin,
        confirmed=origin == NoteOrigin.user,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link, ["from_note", "to_note"])  # async: no lazy loads later
    return link


async def candidate_notes(
    db: AsyncSession, note: Note, threshold: float, limit: int = 5
) -> list[Note]:
    """Same-track notes with similar embeddings that are not already linked to `note`."""
    if note.embedding is None:
        return []
    distance = Note.embedding.cosine_distance(note.embedding)
    rows = (
        await db.execute(
            select(Note, distance.label("distance"))
            .where(
                Note.track_id == note.track_id,
                Note.id != note.id,
                Note.embedding.is_not(None),
            )
            .order_by(distance)
            .limit(limit)
        )
    ).all()
    near = [n for n, dist in rows if 1.0 - float(dist) >= threshold]
    return [n for n in near if not await pair_is_linked(db, note.id, n.id)]


async def propose_links(
    db: AsyncSession,
    llm: LLMClient,
    note: Note,
    settings: Settings,
    session_id: uuid.UUID | None = None,
) -> list[NoteLink]:
    """Ask the model how the note relates to its nearest neighbours; store assistant links."""
    candidates = await candidate_notes(db, note, settings.link_similarity)
    if not candidates:
        return []
    listing = "\n".join(f"[{i}] {c.title}: {c.body_md}" for i, c in enumerate(candidates, 1))
    proposals = await llm.complete_structured(
        "deep",
        system=load_prompt("links").text,
        user=f"NEW:\n{note.title}: {note.body_md}\n\nCANDIDATES:\n{listing}",
        schema=LinkProposals,
        session_id=session_id,
    )
    created: list[NoteLink] = []
    for p in proposals.links[: settings.max_links_per_note]:
        if not 1 <= p.candidate <= len(candidates):
            continue  # the model named a candidate that does not exist
        other = candidates[p.candidate - 1]
        if await pair_is_linked(db, note.id, other.id):
            continue
        from_id, to_id = (note.id, other.id) if p.direction == "to" else (other.id, note.id)
        created.append(
            await create_link(
                db,
                from_note_id=from_id,
                to_note_id=to_id,
                kind=LinkKind(p.kind),
                origin=NoteOrigin.assistant,  # unconfirmed until the user accepts it
            )
        )
    return created

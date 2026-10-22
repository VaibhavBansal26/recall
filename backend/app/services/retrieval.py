"""Hybrid retrieval over notes: vector similarity fused with keyword (full-text) rank."""

import uuid
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LinkKind, Note, NoteLink, Track
from app.embeddings import Embedder

RRF_K = 60  # reciprocal rank fusion constant
MIN_VECTOR_SIMILARITY = 0.2  # below this a vector hit is noise, not a match


async def hybrid_search(
    db: AsyncSession,
    embedder: Embedder,
    *,
    track_slug: str,
    query: str,
    limit: int = 6,
    pool: int = 12,
) -> list[Note]:
    """Notes that match `query` by meaning or by words, best first (reciprocal rank fusion)."""
    track_ids = select(Track.id).where(Track.slug == track_slug)
    vector = (await embedder.embed([query]))[0]

    distance = Note.embedding.cosine_distance(vector)
    vec_rows = (
        await db.execute(
            select(Note, distance.label("d"))
            .where(Note.track_id.in_(track_ids), Note.embedding.is_not(None))
            .order_by(distance)
            .limit(pool)
        )
    ).all()
    vector_hits = [n for n, d in vec_rows if 1.0 - float(d) >= MIN_VECTOR_SIMILARITY]

    doc = func.to_tsvector("english", Note.title + " " + Note.body_md)
    tsq = func.plainto_tsquery("english", query)
    kw_rows = (
        await db.execute(
            select(Note)
            .where(Note.track_id.in_(track_ids), doc.op("@@")(tsq))
            .order_by(func.ts_rank(doc, tsq).desc())
            .limit(pool)
        )
    ).scalars()
    keyword_hits = list(kw_rows)

    score: dict[uuid.UUID, float] = defaultdict(float)
    notes: dict[uuid.UUID, Note] = {}
    for hits in (vector_hits, keyword_hits):
        for rank, note in enumerate(hits):
            score[note.id] += 1.0 / (RRF_K + rank + 1)
            notes[note.id] = note
    ordered = sorted(notes, key=lambda i: score[i], reverse=True)
    return [notes[i] for i in ordered[:limit]]


async def order_by_prerequisites(db: AsyncSession, notes: list[Note]) -> list[Note]:
    """Reorder so a note comes after the notes it depends on (prerequisite links).

    Stable: notes without constraints keep their relevance order. A cycle falls back to the
    given order for the notes caught in it.
    """
    ids = {n.id for n in notes}
    links = (
        await db.execute(
            select(NoteLink).where(
                NoteLink.kind == LinkKind.prerequisite,
                NoteLink.from_note_id.in_(ids),
                NoteLink.to_note_id.in_(ids),
            )
        )
    ).scalars()
    needs: dict[uuid.UUID, set[uuid.UUID]] = {n.id: set() for n in notes}
    for link in links:
        needs[link.to_note_id].add(link.from_note_id)

    ordered: list[Note] = []
    done: set[uuid.UUID] = set()
    remaining = list(notes)
    while remaining:
        ready = next((n for n in remaining if needs[n.id] <= done), None)
        if ready is None:  # cycle
            ordered.extend(remaining)
            break
        ordered.append(ready)
        done.add(ready.id)
        remaining.remove(ready)
    return ordered

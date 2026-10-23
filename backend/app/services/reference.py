"""Reference material to check an explanation against: the learner's notes, and the text of a source
(such as a PDF) when the notebook was built from one."""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Note, Notebook, SourceChunk
from app.embeddings import Embedder
from app.services import notebooks as notebooks_svc
from app.services import retrieval
from app.services.sessions import get_track

MAX_CHARS = 7000
MAX_CHUNKS = 5


@dataclass
class Reference:
    text: str = ""
    names: list[str] = field(default_factory=list)  # what it was drawn from, for speaking
    has_source: bool = False

    @property
    def empty(self) -> bool:
        return not self.text.strip()

    def about(self) -> str:
        if not self.names:
            return "your notes"
        shown = ", ".join(self.names[:2])
        return f"your notes ({shown})" if not self.has_source else f"your notes and {shown}"


def _note_block(notes: list[Note]) -> str:
    return "\n".join(f"- {n.title}: {n.body_md}" for n in notes)


async def gather(
    db: AsyncSession,
    embedder: Embedder,
    *,
    track_slug: str,
    topic: str,
    notebook_id: uuid.UUID | None = None,
) -> Reference:
    """Notes (and source text) about `topic`: the named or open notebook, else a search."""
    book: Notebook | None = None
    track = await get_track(db, track_slug)
    if track is not None and topic:
        book = await notebooks_svc.find(db, track.id, topic)
    if book is None and notebook_id is not None:
        book = await notebooks_svc.get_notebook(db, notebook_id)

    if book is not None:
        notes = await notebooks_svc.notes_in(db, book.id)
        text = _note_block(notes)
        names = [book.name]
        has_source = False
        if book.source_id is not None:
            vector = (await embedder.embed([topic or book.name]))[0]
            chunks = (
                await db.execute(
                    select(SourceChunk)
                    .where(SourceChunk.source_id == book.source_id)
                    .order_by(SourceChunk.embedding.cosine_distance(vector))
                    .limit(MAX_CHUNKS)
                )
            ).scalars()
            source_text = "\n".join(c.text for c in chunks)
            if source_text:
                text += f"\n\nSOURCE TEXT:\n{source_text}"
                has_source = True
        return Reference(text[:MAX_CHARS], names, has_source)

    if not topic:
        return Reference()
    found = await retrieval.hybrid_search(db, embedder, track_slug=track_slug, query=topic, limit=6)
    return Reference(_note_block(found)[:MAX_CHARS], [n.title for n in found[:2]], False)

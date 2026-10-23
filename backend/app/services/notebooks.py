"""Notebooks: named files of notes inside a track (dsa / "Binary search")."""

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LOCAL_USER_ID
from app.db.models import Note, Notebook, NotebookKind, Track


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def display_name(name: str) -> str:
    """Tidy a spoken name for display: trim, collapse spaces, capitalise the first letter."""
    cleaned = re.sub(r"\s+", " ", name).strip(" .,:;-\"'")
    return cleaned[:1].upper() + cleaned[1:]


async def get_notebook(db: AsyncSession, notebook_id: uuid.UUID) -> Notebook | None:
    return (
        await db.execute(select(Notebook).where(Notebook.id == notebook_id))
    ).scalar_one_or_none()


async def get_or_create(
    db: AsyncSession,
    track: Track,
    name: str,
    kind: NotebookKind = NotebookKind.notes,
    source_id: uuid.UUID | None = None,
) -> tuple[Notebook, bool]:
    """The notebook with this name in the track (case and punctuation ignored), made if missing."""
    slug = slugify(name)
    if not slug:
        raise ValueError("A notebook needs a name")
    existing = (
        await db.execute(
            select(Notebook).where(Notebook.track_id == track.id, Notebook.slug == slug)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False
    notebook = Notebook(
        user_id=LOCAL_USER_ID,
        track_id=track.id,
        track=track,
        name=display_name(name),
        slug=slug,
        kind=kind,
        source_id=source_id,
    )
    db.add(notebook)
    await db.commit()
    return notebook, True


async def find(db: AsyncSession, track_id: uuid.UUID, query: str) -> Notebook | None:
    """Best match for a spoken name: exact, else one that contains it (or it contains), else the
    one sharing the most words. None when nothing is close."""
    q = slugify(query)
    if not q:
        return None
    books = list(
        (await db.execute(select(Notebook).where(Notebook.track_id == track_id))).scalars()
    )
    for book in books:
        if book.slug == q:
            return book
    contained = [b for b in books if q in b.slug or b.slug in q]
    if contained:
        return min(contained, key=lambda b: abs(len(b.slug) - len(q)))
    words = set(q.split())
    scored = [(len(words & set(b.slug.split())), b) for b in books]
    scored = [(n, b) for n, b in scored if n]
    return max(scored, key=lambda p: p[0])[1] if scored else None


async def list_with_counts(
    db: AsyncSession, track_slug: str | None = None
) -> list[tuple[Notebook, int]]:
    count = func.count(Note.id)
    query = (
        select(Notebook, count)
        .outerjoin(Note, Note.notebook_id == Notebook.id)
        .group_by(Notebook.id)
        .order_by(Notebook.updated_at.desc())
    )
    if track_slug:
        query = query.join(Track, Track.id == Notebook.track_id).where(Track.slug == track_slug)
    return [(b, int(n)) for b, n in (await db.execute(query)).all()]


async def notes_in(db: AsyncSession, notebook_id: uuid.UUID) -> list[Note]:
    """Oldest first, which is the order the learner built them in."""
    return list(
        (
            await db.execute(
                select(Note).where(Note.notebook_id == notebook_id).order_by(Note.created_at)
            )
        ).scalars()
    )


async def count_notes(db: AsyncSession, notebook_id: uuid.UUID) -> int:
    return int(
        (
            await db.execute(select(func.count(Note.id)).where(Note.notebook_id == notebook_id))
        ).scalar_one()
    )


async def rename(db: AsyncSession, notebook: Notebook, name: str) -> Notebook:
    slug = slugify(name)
    if not slug:
        raise ValueError("A notebook needs a name")
    clash = (
        await db.execute(
            select(Notebook.id).where(
                Notebook.track_id == notebook.track_id,
                Notebook.slug == slug,
                Notebook.id != notebook.id,
            )
        )
    ).first()
    if clash is not None:
        raise ValueError("Another notebook in this track already has that name")
    notebook.name, notebook.slug = display_name(name), slug
    notebook.updated_at = datetime.now(UTC)
    await db.commit()
    return notebook


async def delete(db: AsyncSession, notebook: Notebook) -> None:
    """Delete the notebook; its notes stay (unfiled)."""
    await db.delete(notebook)
    await db.commit()


async def touch(db: AsyncSession, notebook_id: uuid.UUID) -> None:
    notebook = await get_notebook(db, notebook_id)
    if notebook is not None:
        notebook.updated_at = datetime.now(UTC)
        await db.commit()

"""What Aria knows about the learner's notes right now: read fresh from the database each turn, so a
note or notebook added a moment ago (here, on another device, or by an upload) is already known."""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Note, Notebook, Track

MAX_NOTEBOOKS = 15
MAX_RECENT = 10


@dataclass
class Snapshot:
    track_name: str
    notebooks: list[tuple[str, str, int]] = field(default_factory=list)  # name, kind, notes
    unfiled: int = 0
    recent_titles: list[str] = field(default_factory=list)
    other_tracks: list[tuple[str, int]] = field(default_factory=list)  # track name, notes
    active: str | None = None

    def render(self) -> str:
        lines = [f"Current track: {self.track_name}."]
        lines.append(
            f"Open notebook (new notes go here): {self.active}."
            if self.active
            else "No notebook is open."
        )
        if self.notebooks:
            lines.append("Notebooks in this track:")
            lines += [f"- {n} ({kind}, {count} notes)" for n, kind, count in self.notebooks]
        else:
            lines.append("There are no notebooks in this track yet.")
        if self.unfiled:
            lines.append(f"Notes not in any notebook: {self.unfiled}.")
        if self.recent_titles:
            lines.append("Most recent notes: " + "; ".join(self.recent_titles) + ".")
        if self.other_tracks:
            lines.append(
                "Other tracks: " + ", ".join(f"{n} ({c} notes)" for n, c in self.other_tracks) + "."
            )
        return "\n".join(lines)


async def snapshot(
    db: AsyncSession, track_slug: str, active_notebook_id: uuid.UUID | None = None
) -> Snapshot:
    track = (await db.execute(select(Track).where(Track.slug == track_slug))).scalar_one_or_none()
    if track is None:
        return Snapshot(track_name=track_slug)
    rows = (
        await db.execute(
            select(Notebook, func.count(Note.id))
            .outerjoin(Note, Note.notebook_id == Notebook.id)
            .where(Notebook.track_id == track.id)
            .group_by(Notebook.id)
            .order_by(Notebook.updated_at.desc())
            .limit(MAX_NOTEBOOKS)
        )
    ).all()
    unfiled = (
        await db.execute(
            select(func.count(Note.id)).where(Note.track_id == track.id, Note.notebook_id.is_(None))
        )
    ).scalar_one()
    recent = (
        await db.execute(
            select(Note.title)
            .where(Note.track_id == track.id)
            .order_by(Note.created_at.desc())
            .limit(MAX_RECENT)
        )
    ).scalars()
    others = (
        await db.execute(
            select(Track.name, func.count(Note.id))
            .join(Note, Note.track_id == Track.id)
            .where(Track.id != track.id)
            .group_by(Track.name)
        )
    ).all()
    active = None
    if active_notebook_id is not None:
        active = next((b.name for b, _ in rows if b.id == active_notebook_id), None)
    return Snapshot(
        track_name=track.name,
        notebooks=[(b.name, b.kind.value, int(n)) for b, n in rows],
        unfiled=int(unfiled),
        recent_titles=list(recent),
        other_tracks=[(n, int(c)) for n, c in others],
        active=active,
    )


@dataclass(frozen=True)
class NewNotebook:
    id: uuid.UUID
    name: str
    track_name: str
    kind: str
    notes: int


async def all_notebook_ids(db: AsyncSession) -> set[uuid.UUID]:
    return set((await db.execute(select(Notebook.id))).scalars())


async def notebooks_not_in(db: AsyncSession, seen: set[uuid.UUID]) -> list[NewNotebook]:
    """Notebooks this connection has not met yet (made on another device, by an upload, ...)."""
    rows = (
        await db.execute(
            select(Notebook, func.count(Note.id))
            .outerjoin(Note, Note.notebook_id == Notebook.id)
            .group_by(Notebook.id)
            .order_by(Notebook.created_at)
        )
    ).all()
    return [
        NewNotebook(b.id, b.name, b.track.name, b.kind.value, int(n))
        for b, n in rows
        if b.id not in seen
    ]


def heads_up(fresh: list[NewNotebook]) -> str:
    """One spoken sentence announcing what appeared."""
    if not fresh:
        return ""
    if len(fresh) == 1:
        nb = fresh[0]
        how = "from a source" if nb.kind == "source" else "in " + nb.track_name
        notes = f" with {nb.notes} note{'s' if nb.notes != 1 else ''}" if nb.notes else ""
        return (
            f"By the way, I noticed a new notes file, {nb.name}, {how}{notes}. "
            "Say recite if you'd like to go through it."
        )
    names = ", ".join(n.name for n in fresh[:3])
    return (
        f"By the way, {len(fresh)} new notes files appeared: {names}. "
        "Say open and the name to use one."
    )

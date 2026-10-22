"""Export notes as Markdown files (for the nightly n8n sync)."""

import re
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Diagram, Note, NoteCitation, NoteLink

_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(title: str) -> str:
    return _SLUG.sub("-", title.lower()).strip("-")[:60] or "note"


def _q(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _iso(value: datetime) -> str:
    return value.isoformat()


async def export_markdown(db: AsyncSession) -> list[tuple[str, str]]:
    """(relative path, content) for every note, one Markdown file each."""
    notes = list((await db.execute(select(Note).order_by(Note.created_at))).scalars())
    links = list((await db.execute(select(NoteLink))).scalars())
    diagrams = {d.note_id: d for d in (await db.execute(select(Diagram))).scalars()}
    cites: dict[uuid.UUID, list[NoteCitation]] = {}
    for c in (await db.execute(select(NoteCitation))).scalars():
        cites.setdefault(c.note_id, []).append(c)

    by_note: dict[uuid.UUID, list[str]] = {}
    for link in links:
        by_note.setdefault(link.from_note_id, []).append(
            f"- {link.kind.value.replace('_', ' ')} → [[{link.to_note.title}]]"
            + ("" if link.confirmed else " (unconfirmed)")
        )
        by_note.setdefault(link.to_note_id, []).append(
            f"- [[{link.from_note.title}]] → {link.kind.value.replace('_', ' ')}"
            + ("" if link.confirmed else " (unconfirmed)")
        )

    files = []
    for note in notes:
        lines = [
            "---",
            f"title: {_q(note.title)}",
            f"track: {note.track.slug}",
            f"origin: {note.origin.value}",
            f"confirmed: {str(note.confirmed).lower()}",
            f"fragile: {str(note.fragile).lower()}",
            f"created: {_iso(note.created_at)}",
            "---",
            f"# {note.title}",
            "",
            note.body_md.strip(),
            "",
        ]
        if note.id in by_note:
            lines += ["## Links", *by_note[note.id], ""]
        if note.id in cites:
            lines += ["## Sources"]
            for c in cites[note.id]:
                lines.append(f"- “{c.quote}” (chunk {c.chunk.idx}, source {c.source_id})")
            lines.append("")
        if (diagram := diagrams.get(note.id)) is not None and diagram.kind.value == "mermaid":
            lines += ["## Diagram", "```mermaid", diagram.source, "```", ""]
        files.append(
            (f"{note.track.slug}/{slugify(note.title)}-{str(note.id)[:8]}.md", "\n".join(lines))
        )
    return files

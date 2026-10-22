"""Enrich: after capture, give each touched note a diagram and propose links to related notes."""

import logging

from app.agent.deps import AgentDeps
from app.agent.state import AgentState, DiagramItem, LinkItem
from app.db.models import NoteLink
from app.services import notes as notes_svc
from app.services.diagrams import build_diagram, save_diagram
from app.services.links import propose_links

log = logging.getLogger(__name__)


def link_item(link: NoteLink) -> LinkItem:
    return LinkItem(
        id=link.id,
        from_note_id=link.from_note_id,
        to_note_id=link.to_note_id,
        from_title=link.from_note.title,
        to_title=link.to_note.title,
        kind=link.kind.value,
        origin=link.origin.value,
        confirmed=link.confirmed,
    )


async def enrich_node(deps: AgentDeps, state: AgentState) -> AgentState:
    diagrams: list[DiagramItem] = []
    links: list[LinkItem] = []
    for item in state.captured:
        async with deps.sessionmaker() as db:
            note = await notes_svc.get_note(db, item.note_id)
            if note is None:  # undone while we were working
                continue
            try:
                kind, source = await build_diagram(
                    deps.llm, title=note.title, body_md=note.body_md, session_id=state.session_id
                )
                await save_diagram(db, note.id, kind, source)
                diagrams.append(DiagramItem(note_id=note.id, kind=kind.value, source=source))
            except Exception:
                log.exception("diagram generation failed for note %s", note.id)
            try:
                created = await propose_links(
                    db, deps.llm, note, deps.settings, session_id=state.session_id
                )
                links += [link_item(link) for link in created]
            except Exception:
                log.exception("link proposal failed for note %s", note.id)
    return state.model_copy(update={"diagrams": diagrams, "links": links})

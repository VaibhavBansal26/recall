from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import Db
from app.api.links import to_link_out
from app.db.models import Diagram
from app.schemas import GraphNode, GraphOut
from app.services import links as links_svc
from app.services import notes as notes_svc
from app.services import reviews as reviews_svc

router = APIRouter(prefix="/api")


@router.get("/graph", response_model=GraphOut)
async def graph(db: Db, track: str | None = None) -> GraphOut:
    """Nodes and edges for the React Flow memory map."""
    notes = await notes_svc.list_notes(db, track, limit=1000)
    with_diagram = set((await db.execute(select(Diagram.note_id))).scalars())
    strengths = await reviews_svc.note_strengths(db, track_slug=track)
    ids = {n.id for n in notes}
    edges = [
        to_link_out(link)
        for link in await links_svc.links_for_track(db, track)
        if link.from_note_id in ids and link.to_note_id in ids
    ]
    return GraphOut(
        nodes=[
            GraphNode(
                id=n.id,
                title=n.title,
                body_md=n.body_md,
                track=n.track.slug,
                origin=n.origin,
                confirmed=n.confirmed,
                strength=strengths.get(n.id),
                fragile=n.fragile,
                has_diagram=n.id in with_diagram,
            )
            for n in notes
        ],
        edges=edges,
    )

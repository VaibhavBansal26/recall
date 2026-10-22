import uuid

from fastapi import APIRouter, HTTPException, Request

from app.api.deps import Db
from app.schemas import SessionCreate, SessionDetail, SessionOut, TrackOut
from app.services import sessions as svc

router = APIRouter(prefix="/api")


@router.get("/tracks", response_model=list[TrackOut])
async def list_tracks(db: Db) -> list[TrackOut]:
    return [
        TrackOut(slug=t.slug, name=t.name, description=t.config.get("description", ""))
        for t in await svc.list_tracks(db)
    ]


@router.post("/sessions", response_model=SessionOut, status_code=201)
async def create_session(body: SessionCreate, db: Db) -> SessionOut:
    track = await svc.get_track(db, body.track)
    if track is None:
        raise HTTPException(status_code=404, detail=f"Unknown track {body.track!r}")
    return svc.to_session_out(await svc.create_session(db, track))


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def get_session(session_id: uuid.UUID, db: Db, request: Request) -> SessionDetail:
    session = await svc.get_session(db, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return svc.to_session_detail(session, request.app.state.usage.for_session(session_id))

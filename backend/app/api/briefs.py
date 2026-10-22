import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Response

from app.api.deps import Db
from app.config import get_settings
from app.db.models import DailyBrief
from app.schemas import BriefOut, BriefQuestion
from app.services import briefs as svc
from app.services.sessions import get_track

# Cookie-guarded (the browser) and machine-guarded (n8n's morning cron) routers.
router = APIRouter(prefix="/api")
machine_router = APIRouter(prefix="/api")


def user_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().user_timezone)


async def to_brief_out(db: Db, brief: DailyBrief, *, created: bool = True) -> BriefOut:
    items = await svc.brief_items(db, brief)
    return BriefOut(
        id=brief.id,
        date=brief.brief_date,
        status=brief.status,
        track=brief.track.slug,
        due_today=brief.due_today,
        questions=[
            BriefQuestion(
                item_id=i.id,
                note_id=i.note_id,
                note_title=i.note.title,
                kind=i.prompt_kind,
                prompt=i.prompt,
            )
            for i in items
        ],
        created=created,
        started_at=brief.started_at,
        completed_at=brief.completed_at,
    )


@machine_router.post("/sessions/daily-brief", response_model=BriefOut, status_code=201)
async def daily_brief(
    db: Db, response: Response, track: str | None = None, force: bool = False
) -> BriefOut:
    """Build today's brief (the n8n morning cron calls this). Safe to call repeatedly."""
    settings = get_settings()
    slug = track or settings.default_track
    if await get_track(db, slug) is None:
        raise HTTPException(status_code=404, detail=f"Unknown track {slug!r}")
    brief, created = await svc.create_brief(
        db,
        track_slug=slug,
        now=datetime.now(UTC),
        tz=user_tz(),
        questions=settings.brief_questions,
        force=force,
    )
    if not created:
        response.status_code = 200
    return await to_brief_out(db, brief, created=created)


@router.get("/briefs/ready", response_model=BriefOut | None)
async def ready_brief(db: Db) -> BriefOut | None:
    """Today's brief if it is waiting to be started: the frontend's "Your brief is ready"."""
    brief = await svc.ready_brief(db, now=datetime.now(UTC), tz=user_tz())
    return await to_brief_out(db, brief, created=False) if brief else None


@router.get("/briefs/{brief_id}", response_model=BriefOut)
async def get_brief(brief_id: uuid.UUID, db: Db) -> BriefOut:
    brief = await svc.get_brief(db, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    return await to_brief_out(db, brief, created=False)

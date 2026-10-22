from fastapi import APIRouter, Response
from sqlalchemy import text

from app.api.deps import Db
from app.config import get_settings
from app.schemas import HealthOut

router = APIRouter()


@router.get("/healthz", response_model=HealthOut)
async def healthz(db: Db, response: Response) -> HealthOut:
    try:
        await db.execute(text("SELECT 1"))
        db_state = "up"
    except Exception:
        db_state = "down"
        response.status_code = 503
    return HealthOut(
        status="ok" if db_state == "up" else "degraded",
        db=db_state,
        voice_provider=get_settings().voice_provider,
    )

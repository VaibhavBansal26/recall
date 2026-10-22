from fastapi import APIRouter

from app.api.deps import Db
from app.schemas import ExportFile, ExportOut
from app.services.export import export_markdown

router = APIRouter(prefix="/api")


@router.get("/export", response_model=ExportOut)
async def export(db: Db) -> ExportOut:
    """Every note as a Markdown file, for the nightly sync workflow."""
    return ExportOut(files=[ExportFile(path=p, content=c) for p, c in await export_markdown(db)])

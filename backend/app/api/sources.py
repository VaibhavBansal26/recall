import asyncio
import hashlib
import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from sqlalchemy import select

from app.api.deps import Db
from app.db.models import CaptureEvent, NoteCitation, Source, SourceKind, SourceStatus
from app.ingest import IngestError
from app.ingest.extract import pdf_to_text
from app.schemas import (
    CitationOut,
    SourceCreate,
    SourceDetail,
    SourceItemOut,
    SourceOut,
    SourceSummaryOut,
    TrackChoice,
)
from app.services import ingest as svc
from app.services.ingest import IngestRunner
from app.services.sessions import get_track

router = APIRouter(prefix="/api")

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _runner(request: Request) -> IngestRunner:
    runner: IngestRunner = request.app.state.ingest
    return runner


async def to_source_out(
    db: Db, source: Source, *, deduplicated: bool = False, with_headline: bool = True
) -> SourceOut:
    headline = None
    if with_headline and source.status in (SourceStatus.ready, SourceStatus.approved):
        summary = await svc.summarize(db, source)
        headline = summary.headline(source.track.name if source.track else None)
    return SourceOut(
        id=source.id,
        kind=source.kind,
        uri=source.uri,
        title=source.title,
        status=source.status,
        stage=source.stage,
        error=source.error,
        track=source.track.slug if source.track else None,
        track_name=source.track.name if source.track else None,
        topic=source.topic,
        suggested_track=source.suggested_track,
        track_confidence=source.track_confidence,
        headline=headline,
        created_at=source.created_at,
        updated_at=source.updated_at,
        deduplicated=deduplicated,
    )


async def _require_track(db: Db, slug: str | None) -> None:
    if slug and await get_track(db, slug) is None:
        raise HTTPException(status_code=404, detail=f"Unknown track {slug!r}")


@router.post("/sources", response_model=SourceOut, status_code=201)
async def create_source(
    body: SourceCreate, db: Db, request: Request, response: Response
) -> SourceOut:
    """Queue a link or pasted text for ingestion. The same link/text twice is not duplicated."""
    await _require_track(db, body.track_hint)
    try:
        source, queued = await svc.submit_source(
            db,
            kind=body.kind,
            uri=body.uri,
            text=body.text,
            title=body.title,
            track_hint=body.track_hint,
        )
    except IngestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if queued:
        _runner(request).start(source.id)
    else:
        response.status_code = 200  # already known: returned as is
    return await to_source_out(db, source, deduplicated=not queued)


@router.post("/sources/upload", response_model=SourceOut, status_code=201)
async def upload_source(
    db: Db,
    request: Request,
    response: Response,
    file: Annotated[UploadFile, File()],
    track_hint: Annotated[str | None, Form()] = None,
) -> SourceOut:
    """Upload a PDF (used by the n8n inbox workflow)."""
    await _require_track(db, track_hint)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="That file is too large (20 MB limit).")
    if data[:5] != b"%PDF-":
        raise HTTPException(status_code=415, detail="Only PDF files can be uploaded.")
    digest = hashlib.sha256(data).hexdigest()
    try:
        existing = await svc.find_source(db, f"sha256:{digest}")
        if existing is not None and existing.status != SourceStatus.failed:
            response.status_code = 200
            return await to_source_out(db, existing, deduplicated=True)
        title, text = await asyncio.to_thread(pdf_to_text, data)
        source, queued = await svc.submit_source(
            db,
            kind=SourceKind.pdf,
            title=title or (file.filename or "PDF"),
            track_hint=track_hint,
            prepared_text=text,
            content_hash=digest,
        )
    except IngestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if queued:
        _runner(request).start(source.id)
    return await to_source_out(db, source, deduplicated=not queued)


@router.get("/sources", response_model=list[SourceOut])
async def list_sources(db: Db, limit: int = 50) -> list[SourceOut]:
    rows = (
        await db.execute(
            select(Source).order_by(Source.created_at.desc()).limit(max(1, min(limit, 200)))
        )
    ).scalars()
    return [await to_source_out(db, s) for s in rows]


async def _get(db: Db, source_id: uuid.UUID) -> Source:
    source = (await db.execute(select(Source).where(Source.id == source_id))).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.get("/sources/{source_id}", response_model=SourceDetail)
async def get_source(source_id: uuid.UUID, db: Db) -> SourceDetail:
    source = await _get(db, source_id)
    base = await to_source_out(db, source)
    summary = await svc.summarize(db, source)

    citations: dict[uuid.UUID, list[CitationOut]] = {}
    for c in (
        await db.execute(select(NoteCitation).where(NoteCitation.source_id == source_id))
    ).scalars():
        citations.setdefault(c.note_id, []).append(
            CitationOut(chunk_idx=c.chunk.idx, quote=c.quote)
        )

    events = (
        await db.execute(
            select(CaptureEvent)
            .where(CaptureEvent.source_id == source_id)
            .order_by(CaptureEvent.created_at)
        )
    ).scalars()
    items = []
    for e in events:
        note = e.note
        items.append(
            SourceItemOut(
                event_id=e.id,
                action=e.action.value,
                note_id=e.note_id,
                title=note.title if note else None,
                body_md=note.body_md if note else None,
                before_body_md=(e.before or {}).get("body_md"),
                origin=note.origin if note else None,
                confirmed=note.confirmed if note else False,
                undone=e.undone,
                citations=citations.get(e.note_id, []) if e.note_id else [],
            )
        )
    return SourceDetail(
        **base.model_dump(),
        summary=SourceSummaryOut(
            created=summary.created,
            merged=summary.merged,
            linked=summary.linked,
            chunks=summary.chunks,
        ),
        items=items,
    )


@router.post("/sources/{source_id}/track", response_model=SourceOut)
async def choose_track(
    source_id: uuid.UUID, body: TrackChoice, db: Db, request: Request
) -> SourceOut:
    """Answer "which track does this belong to?" when classification was not confident."""
    source = await _get(db, source_id)
    if source.status != SourceStatus.needs_track:
        raise HTTPException(status_code=409, detail="This source is not waiting for a track")
    try:
        await svc.set_track(db, source, body.track)
    except IngestError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _runner(request).start(source.id)
    return await to_source_out(db, source)


@router.post("/sources/{source_id}/retry", response_model=SourceOut)
async def retry_source(source_id: uuid.UUID, db: Db, request: Request) -> SourceOut:
    source = await _get(db, source_id)
    if source.status != SourceStatus.failed:
        raise HTTPException(status_code=409, detail="Only a failed source can be retried")
    source.status, source.error, source.stage = SourceStatus.queued, None, None
    await db.commit()
    _runner(request).start(source.id)
    return await to_source_out(db, source)


@router.post("/sources/{source_id}/approve", response_model=SourceOut)
async def approve_source(source_id: uuid.UUID, db: Db) -> SourceOut:
    """Accept what was filed: its notes become confirmed (and eligible for quizzes)."""
    source = await _get(db, source_id)
    if source.status != SourceStatus.ready:
        raise HTTPException(status_code=409, detail="Nothing to approve yet")
    await svc.approve(db, source)
    return await to_source_out(db, source)

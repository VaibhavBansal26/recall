"""The ingestion pipeline: fetch, chunk, embed, classify, extract cited notes, file, enrich."""

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.deps import AgentDeps
from app.agent.nodes.capture import capture_item
from app.agent.nodes.enrich import enrich_node
from app.agent.prompts import load_prompt
from app.agent.schemas import SourceNotes, TrackClassification
from app.agent.state import AgentState, CaptureItem
from app.db.models import (
    CaptureEvent,
    Note,
    NotebookKind,
    NoteCitation,
    NoteLink,
    NoteOrigin,
    Source,
    SourceChunk,
    SourceKind,
    SourceStatus,
    Track,
)
from app.ingest import IngestError
from app.ingest.chunking import chunk_text
from app.ingest.citations import normalize, quote_in_chunk
from app.ingest.extract import html_to_text, pdf_to_text, youtube_to_text
from app.ingest.fetch import SafeFetcher
from app.ingest.urls import detect_kind, normalize_url, youtube_video_id
from app.services import notebooks as notebooks_svc
from app.services.capture import file_candidate
from app.services.sessions import get_track, list_tracks
from app.tracks import guidance_for

log = logging.getLogger(__name__)

EMBED_BATCH = 64
GROUP_SIZE = 3  # chunks shown to the model per extraction call
ENRICH_BATCH = 3  # notes per enrichment worker


@dataclass
class IngestContext:
    deps: AgentDeps
    fetcher: SafeFetcher


@dataclass
class Candidate:
    title: str
    body_md: str
    citations: list[tuple[int, str]] = field(default_factory=list)  # (chunk idx, verbatim quote)


# ------------------------------------------------------------------ submitting


async def find_source(db: AsyncSession, uri: str) -> Source | None:
    return (await db.execute(select(Source).where(Source.uri == uri))).scalar_one_or_none()


async def submit_source(
    db: AsyncSession,
    *,
    kind: SourceKind | None = None,
    uri: str | None = None,
    text: str | None = None,
    title: str | None = None,
    track_hint: str | None = None,
    prepared_text: str | None = None,
    content_hash: str | None = None,
) -> tuple[Source, bool]:
    """Create a source, or return the existing one for the same link/content.

    Returns (source, queued). `queued` is True when a job should be started: a new source, or a
    previous attempt that failed. Submitting the same thing twice never duplicates it.
    """
    if prepared_text is not None:  # an uploaded PDF whose text was already extracted
        kind = kind or SourceKind.pdf
        canonical, raw = f"sha256:{content_hash}", prepared_text
    elif text is not None:
        raw = text.strip()
        if len(raw.split()) < 30:
            raise IngestError("That text is too short to file (at least about 30 words).")
        kind = SourceKind.text
        canonical = "sha256:" + hashlib.sha256(raw.encode()).hexdigest()
    elif uri:
        canonical, raw = normalize_url(uri), None
        detected = detect_kind(canonical)
        kind = detected if kind in (None, SourceKind.url) else kind
    else:
        raise IngestError("Give a link or some text.")

    existing = await find_source(db, canonical)
    if existing is not None:
        if existing.status == SourceStatus.failed:
            existing.status, existing.error, existing.stage = SourceStatus.queued, None, None
            await db.commit()
            return existing, True
        return existing, False

    assert kind is not None
    source = Source(
        kind=kind,
        uri=canonical,
        title=title or (raw.splitlines()[0][:100] if raw else None),
        raw_text=raw,
        track_hint=track_hint,
        status=SourceStatus.queued,
    )
    db.add(source)
    await db.commit()
    return source, True


async def set_track(db: AsyncSession, source: Source, slug: str) -> Source:
    """The user chose a track for a source that needed one; the job resumes from there."""
    track = await get_track(db, slug)
    if track is None:
        raise IngestError(f"Unknown track {slug!r}.")
    source.track_id, source.track_hint = track.id, slug
    source.status, source.error, source.stage = SourceStatus.queued, None, None
    await db.commit()
    return source


# ------------------------------------------------------------------ the job


async def _update(
    sm: async_sessionmaker[AsyncSession], source_id: uuid.UUID, **fields: Any
) -> None:
    async with sm() as db:
        await db.execute(update(Source).where(Source.id == source_id).values(**fields))
        await db.commit()


async def run_ingest(ctx: IngestContext, source_id: uuid.UUID) -> None:
    """Process one source end to end. Never raises: failures land on the source as an error."""
    sm = ctx.deps.sessionmaker
    try:
        await _run(ctx, source_id)
    except IngestError as exc:
        await _update(sm, source_id, status=SourceStatus.failed, stage=None, error=str(exc))
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("ingest failed for %s", source_id)
        await _update(
            sm,
            source_id,
            status=SourceStatus.failed,
            stage=None,
            error="Something went wrong while processing this source. Try again.",
        )


async def _run(ctx: IngestContext, source_id: uuid.UUID) -> None:
    sm = ctx.deps.sessionmaker
    async with sm() as db:
        source = (await db.execute(select(Source).where(Source.id == source_id))).scalar_one()
        kind, uri, raw, title = source.kind, source.uri, source.raw_text, source.title
        track_id, hint = source.track_id, source.track_hint

    # 1. Fetch and extract text.
    if not raw:
        await _update(sm, source_id, status=SourceStatus.fetching, stage="fetching", error=None)
        fetched_title, raw, kind = await _acquire(ctx, kind, uri)
        title = title or fetched_title
        await _update(sm, source_id, raw_text=raw, title=title, kind=kind)

    # 2. Chunk and embed (skipped when resuming).
    await _update(sm, source_id, status=SourceStatus.processing, stage="chunking", error=None)
    chunks = await _ensure_chunks(ctx, source_id, raw)

    # 3. Classify into a track, or stop and ask.
    track: Track | None
    async with sm() as db:
        track = await db.get(Track, track_id) if track_id else None
        if track is None and hint:
            track = await get_track(db, hint)
    if track is None:
        await _update(sm, source_id, stage="classifying")
        track = await _classify(ctx, source_id, title or uri, raw)
        if track is None:
            return  # needs_track
    await _update(sm, source_id, track_id=track.id)

    # 4. Extract cited notes from the chunks.
    await _update(sm, source_id, stage="extracting")
    candidates = await _extract(ctx, source_id, track, title or uri, chunks)

    # 5. File them (merge instead of duplicating), then mark ready for approval.
    await _update(sm, source_id, stage="filing")
    items = await _file(ctx, source_id, track, candidates, chunks)
    await _update(sm, source_id, status=SourceStatus.ready, stage=None)
    log.info("ingest %s: filed %d note(s) from %d chunk(s)", source_id, len(items), len(chunks))

    # 6. Diagrams, link proposals and practice questions (the source is already usable).
    await _enrich(ctx, source_id, track, items)


async def _acquire(
    ctx: IngestContext, kind: SourceKind, uri: str
) -> tuple[str | None, str, SourceKind]:
    if kind == SourceKind.youtube:
        video = youtube_video_id(uri)
        if video is None:
            raise IngestError("That does not look like a YouTube video link.")
        title, text = await youtube_to_text(video, ctx.fetcher)
        return title, text, kind

    fetched = await ctx.fetcher.fetch(uri)
    if fetched.content_type == "application/pdf" or fetched.body[:5] == b"%PDF-":
        title, text = await asyncio.to_thread(pdf_to_text, fetched.body)
        return title, text, SourceKind.pdf
    html = fetched.body.decode("utf-8", errors="replace")
    if fetched.content_type == "text/plain":
        title, text = None, html
    else:
        title, text = html_to_text(html)
    if len(text.split()) < 80:
        raise IngestError("Not enough readable text on that page.")
    return title, text, SourceKind.url


async def _ensure_chunks(ctx: IngestContext, source_id: uuid.UUID, raw: str) -> list[SourceChunk]:
    sm, settings = ctx.deps.sessionmaker, ctx.deps.settings
    async with sm() as db:
        existing = list(
            (
                await db.execute(
                    select(SourceChunk)
                    .where(SourceChunk.source_id == source_id)
                    .order_by(SourceChunk.idx)
                )
            ).scalars()
        )
        if existing:
            return existing
        pieces = chunk_text(raw)[: settings.max_chunks_per_source]
        if not pieces:
            raise IngestError("Not enough text to file.")
        vectors: list[list[float]] = []
        for start in range(0, len(pieces), EMBED_BATCH):
            vectors += await ctx.deps.embedder.embed(pieces[start : start + EMBED_BATCH])
        rows = [
            SourceChunk(source_id=source_id, idx=i, text=t, embedding=v)
            for i, (t, v) in enumerate(zip(pieces, vectors, strict=True))
        ]
        db.add_all(rows)
        await db.commit()
        return rows


async def _classify(ctx: IngestContext, source_id: uuid.UUID, title: str, raw: str) -> Track | None:
    sm, settings = ctx.deps.sessionmaker, ctx.deps.settings
    async with sm() as db:
        tracks = await list_tracks(db)
    if len(tracks) == 1:  # nothing to choose between
        return tracks[0]

    listing = "\n".join(f"- {t.slug}: {t.name}. {t.config.get('description', '')}" for t in tracks)
    opening = " ".join(raw.split()[:2500])
    result = await ctx.deps.llm.complete_structured(
        "fast",
        system=load_prompt("ingest_classify").text,
        user=f"TRACKS:\n{listing}\n\nSOURCE TITLE: {title}\nTEXT:\n{opening}",
        schema=TrackClassification,
        session_id=source_id,
    )
    by_slug = {t.slug: t for t in tracks}
    chosen = by_slug.get(result.track)
    confident = chosen is not None and result.confidence >= settings.track_confidence_min
    await _update(
        sm,
        source_id,
        topic=result.topic,
        suggested_track=chosen.slug if chosen else None,
        track_confidence=result.confidence if chosen else 0.0,
    )
    if confident:
        return chosen
    await _update(sm, source_id, status=SourceStatus.needs_track, stage=None)
    return None


async def _extract(
    ctx: IngestContext,
    source_id: uuid.UUID,
    track: Track,
    title: str,
    chunks: list[SourceChunk],
) -> list[Candidate]:
    """Ask the model for notes per group of chunks, keeping only notes whose quotes check out."""
    settings = ctx.deps.settings
    system = load_prompt("ingest_extract").text + guidance_for(track.slug, "capture")
    sem = asyncio.Semaphore(3)
    groups = [chunks[i : i + GROUP_SIZE] for i in range(0, len(chunks), GROUP_SIZE)]

    async def one(group: list[SourceChunk]) -> list[Candidate]:
        listing = "\n".join(f"[{c.idx}]\n{c.text}\n" for c in group)
        async with sem:
            result = await ctx.deps.llm.complete_structured(
                "deep",
                system=system,
                user=f"TRACK: {track.name}\nSOURCE TITLE: {title}\nCHUNKS:\n{listing}",
                schema=SourceNotes,
                session_id=source_id,
            )
        text_by_idx = {c.idx: c.text for c in group}
        out = []
        for note in result.notes:
            # Never trust the model: a note stays only if a quote is verbatim in a cited chunk.
            cites = [
                (c.chunk, c.quote.strip())
                for c in note.citations
                if c.chunk in text_by_idx and quote_in_chunk(c.quote, text_by_idx[c.chunk])
            ]
            if cites and note.title.strip() and note.body_md.strip():
                out.append(Candidate(note.title.strip(), note.body_md.strip(), cites))
        return out

    seen: set[str] = set()
    candidates: list[Candidate] = []
    for group_result in await asyncio.gather(*(one(g) for g in groups)):
        for cand in group_result:
            key = normalize(cand.title)
            if key not in seen:
                seen.add(key)
                candidates.append(cand)
    return candidates[: settings.max_notes_per_source]


async def _file(
    ctx: IngestContext,
    source_id: uuid.UUID,
    track: Track,
    candidates: list[Candidate],
    chunks: list[SourceChunk],
) -> list[CaptureItem]:
    if not candidates:
        return []
    embeddings = await ctx.deps.embedder.embed([f"{c.title}\n{c.body_md}" for c in candidates])
    chunk_ids = {c.idx: c.id for c in chunks}
    items: list[CaptureItem] = []
    async with ctx.deps.sessionmaker() as db:
        track_row = await get_track(db, track.slug)
        assert track_row is not None
        # Everything a source yields goes into one notebook named after it, so it can be recited.
        source_row = await db.get(Source, source_id)
        notebook_id = None
        if source_row is not None:
            name = source_row.title or source_row.topic or "Imported source"
            book, _ = await notebooks_svc.get_or_create(
                db, track_row, name[:120], NotebookKind.source, source_id=source_id
            )
            notebook_id = book.id
        for cand, embedding in zip(candidates, embeddings, strict=True):
            event, note = await file_candidate(
                ctx.deps,
                db,
                track=track_row,
                title=cand.title,
                body_md=cand.body_md,
                embedding=embedding,
                origin=NoteOrigin.source,
                source_id=source_id,
                usage_id=source_id,
                notebook_id=notebook_id,
            )
            for idx, quote in cand.citations:
                db.add(
                    NoteCitation(
                        note_id=note.id, source_id=source_id, chunk_id=chunk_ids[idx], quote=quote
                    )
                )
            await db.commit()
            items.append(capture_item(event, note))
    return items


async def _enrich(
    ctx: IngestContext, source_id: uuid.UUID, track: Track, items: list[CaptureItem]
) -> None:
    """Diagrams, link proposals and review items for the filed notes, a few notes at a time."""
    batches = [items[i : i + ENRICH_BATCH] for i in range(0, len(items), ENRICH_BATCH)]

    async def run(batch: list[CaptureItem]) -> None:
        state = AgentState(session_id=source_id, track=track.slug, captured=batch)
        await enrich_node(ctx.deps, state)

    results = await asyncio.gather(*(run(b) for b in batches), return_exceptions=True)
    for r in results:
        if isinstance(r, Exception) and not isinstance(r, asyncio.CancelledError):
            log.error("enrich failed for source %s: %r", source_id, r)


# ------------------------------------------------------------------ approval and summary


async def approve(db: AsyncSession, source: Source) -> int:
    """Confirm the notes this source filed. Undone items stay undone. Returns notes confirmed."""
    ids = (
        await db.execute(
            select(CaptureEvent.note_id).where(
                CaptureEvent.source_id == source.id, CaptureEvent.undone.is_(False)
            )
        )
    ).scalars()
    note_ids = [i for i in ids if i is not None]
    if note_ids:
        await db.execute(update(Note).where(Note.id.in_(note_ids)).values(confirmed=True))
    source.status = SourceStatus.approved
    await db.commit()
    return len(note_ids)


@dataclass(frozen=True)
class SourceSummary:
    created: int
    merged: int
    linked: int
    chunks: int

    def headline(self, track_name: str | None) -> str:
        where = f" under {track_name}" if track_name else ""
        if self.created == 0 and self.merged == 0:
            return "Nothing worth filing was found in this source."
        parts = [f"Filed {self.created} note{'s' if self.created != 1 else ''}{where}"]
        if self.merged:
            parts.append(f"merged {self.merged} into existing notes")
        if self.linked:
            parts.append(f"linked {self.linked}")
        return ", ".join(parts) + "."


async def summarize(db: AsyncSession, source: Source) -> SourceSummary:
    events = list(
        (
            await db.execute(
                select(CaptureEvent).where(
                    CaptureEvent.source_id == source.id, CaptureEvent.undone.is_(False)
                )
            )
        ).scalars()
    )
    note_ids = [e.note_id for e in events if e.note_id is not None]
    linked = 0
    if note_ids:
        linked = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(NoteLink)
                    .where(
                        or_(NoteLink.from_note_id.in_(note_ids), NoteLink.to_note_id.in_(note_ids))
                    )
                )
            ).scalar_one()
        )
    chunks = int(
        (
            await db.execute(
                select(func.count())
                .select_from(SourceChunk)
                .where(SourceChunk.source_id == source.id)
            )
        ).scalar_one()
    )
    return SourceSummary(
        created=sum(1 for e in events if e.action.value == "created"),
        merged=sum(1 for e in events if e.action.value == "merged"),
        linked=linked,
        chunks=chunks,
    )


# ------------------------------------------------------------------ the job runner


class IngestRunner:
    """Runs ingestion jobs in the background, a few at a time, and resumes after a restart."""

    def __init__(self, ctx: IngestContext) -> None:
        self.ctx = ctx
        self._sem = asyncio.Semaphore(ctx.deps.settings.ingest_concurrency)
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}

    def start(self, source_id: uuid.UUID) -> None:
        if source_id in self._tasks and not self._tasks[source_id].done():
            return
        task = asyncio.create_task(self._run(source_id))
        self._tasks[source_id] = task

        def forget(_task: asyncio.Task[None]) -> None:
            self._tasks.pop(source_id, None)

        task.add_done_callback(forget)

    async def _run(self, source_id: uuid.UUID) -> None:
        async with self._sem:
            await run_ingest(self.ctx, source_id)

    async def resume_unfinished(self) -> None:
        """After a restart, pick up anything that was mid-flight (the job is resumable)."""
        async with self.ctx.deps.sessionmaker() as db:
            stuck = (
                await db.execute(
                    select(Source.id).where(
                        Source.status.in_(
                            [SourceStatus.queued, SourceStatus.fetching, SourceStatus.processing]
                        )
                    )
                )
            ).scalars()
            for source_id in list(stuck):
                self.start(source_id)

    async def wait_idle(self) -> None:
        await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)

    async def aclose(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)

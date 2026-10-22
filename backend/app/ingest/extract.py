"""Turn fetched material into plain text: web articles, PDFs, YouTube transcripts."""

import asyncio
import io
import json
import re
from collections.abc import Callable
from typing import Any

from bs4 import BeautifulSoup, Tag
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.ingest import IngestError
from app.ingest.fetch import SafeFetcher

MAX_CHARS = 400_000
MAX_PDF_PAGES = 300
MIN_TEXT_CHARS = 200

_NOISE = [
    "script",
    "style",
    "noscript",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "svg",
    "iframe",
]
_BLOCKS = "h1, h2, h3, h4, h5, h6, p, li, pre, blockquote, figcaption"


def _clean(text: str) -> str:
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*(\n\s*)+", "\n\n", text)
    return text.strip()[:MAX_CHARS]


def html_to_text(html: str) -> tuple[str | None, str]:
    """(title, article text). Prefers <article>/<main>, drops navigation and boilerplate."""
    soup = BeautifulSoup(html, "html.parser")
    title = None
    og = soup.find("meta", attrs={"property": "og:title"})
    if isinstance(og, Tag) and og.get("content"):
        title = str(og["content"]).strip()
    elif soup.title and soup.title.string:
        title = soup.title.string.strip()

    for tag in soup(_NOISE):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.select_one("[role=main]") or soup.body
    if root is None:
        return title, ""
    blocks = [b.get_text(" ", strip=True) for b in root.select(_BLOCKS)]
    text = "\n\n".join(b for b in blocks if b)
    if len(text) < MIN_TEXT_CHARS:  # unusual markup: fall back to everything in the container
        text = root.get_text("\n", strip=True)
    return title, _clean(text)


def pdf_to_text(data: bytes) -> tuple[str | None, str]:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise IngestError("That PDF is password protected.")
        pages = [(p.extract_text() or "") for p in reader.pages[:MAX_PDF_PAGES]]
        meta_title = getattr(reader.metadata, "title", None) if reader.metadata else None
    except IngestError:
        raise
    except (PyPdfError, ValueError, KeyError, OSError) as exc:
        raise IngestError("Could not read that PDF.") from exc
    text = _clean("\n\n".join(pages))
    if len(text) < MIN_TEXT_CHARS:
        raise IngestError("No readable text in that PDF (is it a scan?).")
    return (str(meta_title).strip() or None) if meta_title else None, text


TranscriptFetcher = Callable[[str], list[str]]


def _default_transcript(video_id: str) -> list[str]:
    from youtube_transcript_api import YouTubeTranscriptApi

    fetched = YouTubeTranscriptApi().fetch(video_id, languages=("en", "en-US", "en-GB"))
    return [str(snippet.text) for snippet in fetched]


async def youtube_to_text(
    video_id: str,
    fetcher: SafeFetcher,
    transcript: TranscriptFetcher | None = None,
) -> tuple[str | None, str]:
    """(title, transcript). YouTube often blocks cloud IPs, so failures say what to do instead."""
    try:
        snippets = await asyncio.to_thread(transcript or _default_transcript, video_id)
    except Exception as exc:
        raise IngestError(
            "Could not get the transcript (it may be disabled, or YouTube blocked this server). "
            "You can paste the transcript as text instead."
        ) from exc
    text = _clean(re.sub(r"\s+", " ", " ".join(snippets)))
    if len(text) < MIN_TEXT_CHARS:
        raise IngestError("That video has no usable transcript.")

    title = None
    try:  # a title is nice to have; never fail the ingest over it
        oembed = f"https://www.youtube.com/oembed?format=json&url=https://www.youtube.com/watch?v={video_id}"
        data: Any = json.loads((await fetcher.fetch(oembed)).body)
        title = str(data.get("title")) or None
    except Exception:
        title = None
    return title, text

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.db.models import SourceKind
from app.ingest import IngestError

_TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|mc_cid|mc_eid|igshid|ref|ref_src|si)$", re.I)
_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def youtube_video_id(url: str) -> str | None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host not in _YT_HOSTS:
        return None
    if host == "youtu.be":
        candidate = parts.path.lstrip("/").split("/")[0]
    elif parts.path == "/watch":
        candidate = dict(parse_qsl(parts.query)).get("v", "")
    else:
        m = re.match(r"^/(?:shorts|embed|live|v)/([^/?]+)", parts.path)
        candidate = m.group(1) if m else ""
    return candidate if _YT_ID.match(candidate) else None


def normalize_url(url: str) -> str:
    """A canonical form so the same page submitted twice is recognised as one source."""
    url = url.strip()
    # "example.com/x" gets https://, but "javascript:..." or "mailto:..." is a scheme, not a host.
    if "://" not in url and re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:(?!\d)", url):
        raise IngestError("Only http and https links can be ingested.")
    try:
        parts = urlsplit(url if "://" in url else f"https://{url}")
        port = parts.port
    except ValueError as exc:
        raise IngestError("That does not look like a valid link.") from exc
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise IngestError("Only http and https links can be ingested.")

    if video := youtube_video_id(url):
        return f"https://www.youtube.com/watch?v={video}"

    scheme, host = parts.scheme.lower(), parts.hostname.lower()
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = parts.path.rstrip("/") or "/"
    query = urlencode(
        sorted(
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not _TRACKING.match(k)
        )
    )
    return urlunsplit((scheme, netloc, path, query, ""))  # the fragment is dropped


def detect_kind(url: str) -> SourceKind:
    if youtube_video_id(url):
        return SourceKind.youtube
    if urlsplit(url).path.lower().endswith(".pdf"):
        return SourceKind.pdf
    return SourceKind.url

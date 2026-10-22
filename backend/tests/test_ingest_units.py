import asyncio
from typing import Any

import httpx
import pytest

from app.db.models import SourceKind
from app.ingest import IngestError
from app.ingest.chunking import chunk_text
from app.ingest.citations import normalize, quote_in_chunk
from app.ingest.extract import html_to_text, pdf_to_text, youtube_to_text
from app.ingest.fetch import SafeFetcher, is_public
from app.ingest.urls import detect_kind, normalize_url, youtube_video_id
from tests.helpers import ARTICLE_PARAGRAPHS, article_html, make_pdf

# ---- urls ----


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        (
            "https://Example.com/Post/?utm_source=x&b=2&a=1#section",
            "https://example.com/Post?a=1&b=2",
        ),
        ("example.com/post/", "https://example.com/post"),
        ("http://example.com:80/x", "http://example.com/x"),
        ("https://example.com", "https://example.com/"),
        ("https://example.com/p?fbclid=abc&gclid=1", "https://example.com/p"),
        ("https://youtu.be/dQw4w9WgXcQ?si=zzz", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        (
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ&t=30s",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        ),
        (
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        ),
    ],
)
def test_the_same_page_has_one_canonical_form(raw: str, canonical: str) -> None:
    assert normalize_url(raw) == canonical


@pytest.mark.parametrize(
    "bad",
    [
        "ftp://example.com/x",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "",
        "http://[bad",
        "mailto:a@b.co",
    ],
)
def test_only_http_links_are_accepted(bad: str) -> None:
    with pytest.raises(IngestError):
        normalize_url(bad)


def test_kind_detection() -> None:
    assert detect_kind("https://youtu.be/dQw4w9WgXcQ") == SourceKind.youtube
    assert detect_kind("https://example.com/paper.PDF") == SourceKind.pdf
    assert detect_kind("https://example.com/post") == SourceKind.url
    assert youtube_video_id("https://www.youtube.com/watch?v=short") is None


# ---- SSRF guard ----


@pytest.mark.parametrize(
    ("address", "public"),
    [
        ("93.184.216.34", True),
        ("2606:2800:220:1:248:1893:25c8:1946", True),
        ("127.0.0.1", False),
        ("10.0.0.5", False),
        ("172.16.4.4", False),
        ("192.168.1.1", False),
        ("169.254.169.254", False),  # cloud metadata
        ("100.64.0.1", False),  # carrier-grade NAT
        ("0.0.0.0", False),
        ("::1", False),
        ("fc00::1", False),
        ("fe80::1", False),
        ("::ffff:127.0.0.1", False),  # IPv4-mapped loopback
        ("not-an-ip", False),
    ],
)
def test_only_public_addresses_are_allowed(address: str, public: bool) -> None:
    assert is_public(address) is public


def fetcher(handler: Any, hosts: dict[str, list[str]] | None = None, **kw: Any) -> SafeFetcher:
    table = hosts or {}

    async def resolver(host: str) -> list[str]:
        return table.get(host, ["93.184.216.34"])

    return SafeFetcher(resolver=resolver, transport=httpx.MockTransport(handler), **kw)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_a_normal_page_is_fetched() -> None:
    f = fetcher(
        lambda r: httpx.Response(200, text="<html>hi</html>", headers={"content-type": "text/html"})
    )
    got = run(f.fetch("https://example.com/a"))
    assert got.body == b"<html>hi</html>" and got.content_type == "text/html"


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "::1", "192.168.0.10"])
def test_hosts_that_resolve_to_private_addresses_are_refused(ip: str) -> None:
    f = fetcher(lambda r: httpx.Response(200, text="secret"), {"internal.example.com": [ip]})
    with pytest.raises(IngestError, match="not a public website"):
        run(f.fetch("https://internal.example.com/admin"))


def test_a_host_with_any_private_address_is_refused() -> None:
    f = fetcher(lambda r: httpx.Response(200), {"mixed.example.com": ["93.184.216.34", "10.0.0.1"]})
    with pytest.raises(IngestError):
        run(f.fetch("https://mixed.example.com/"))


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/",
    ],
)
def test_ip_literal_urls_to_private_ranges_are_refused(url: str) -> None:
    with pytest.raises(IngestError):
        run(fetcher(lambda r: httpx.Response(200)).fetch(url))


@pytest.mark.parametrize(
    "url", ["http://example.com:8080/", "https://example.com:22/", "ftp://example.com/"]
)
def test_odd_ports_and_schemes_are_refused(url: str) -> None:
    with pytest.raises(IngestError):
        run(fetcher(lambda r: httpx.Response(200)).fetch(url))


def test_a_redirect_into_a_private_address_is_caught_on_the_second_hop() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "https://evil.example.org/x"})
        return httpx.Response(200, text="should never be reached")

    f = fetcher(handler, {"evil.example.org": ["127.0.0.1"]})
    with pytest.raises(IngestError, match="not a public website"):
        run(f.fetch("https://example.com/start"))


def test_a_redirect_to_a_public_page_is_followed_and_loops_are_stopped() -> None:
    def ok(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        return httpx.Response(200, text="new page", headers={"content-type": "text/plain"})

    got = run(fetcher(ok).fetch("https://example.com/old"))
    assert got.url == "https://example.com/new" and got.body == b"new page"

    loop = fetcher(lambda r: httpx.Response(302, headers={"location": "/again"}), max_redirects=3)
    with pytest.raises(IngestError, match="Too many redirects"):
        run(loop.fetch("https://example.com/again"))


def test_size_type_and_status_limits() -> None:
    big = fetcher(
        lambda r: httpx.Response(200, content=b"x" * 5000, headers={"content-type": "text/plain"}),
        max_bytes=1000,
    )
    with pytest.raises(IngestError, match="too large"):
        run(big.fetch("https://example.com/big"))

    binary = fetcher(
        lambda r: httpx.Response(200, content=b"\x00", headers={"content-type": "application/zip"})
    )
    with pytest.raises(IngestError, match="Unsupported content type"):
        run(binary.fetch("https://example.com/f.zip"))

    missing = fetcher(lambda r: httpx.Response(404, text="nope"))
    with pytest.raises(IngestError, match="404"):
        run(missing.fetch("https://example.com/gone"))


def test_timeouts_become_a_friendly_error() -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(IngestError, match="too long"):
        run(fetcher(slow).fetch("https://example.com/slow"))


# ---- extraction ----


def test_html_extraction_keeps_the_article_and_drops_the_chrome() -> None:
    title, text = html_to_text(article_html("RAG in practice"))
    assert title == "RAG in practice"
    assert "Retrieval augmented generation fetches" in text and "cosine similarity" in text
    for noise in (
        "Subscribe",
        "Site header banner",
        "Related posts",
        "Copyright footer",
        "tracking",
    ):
        assert noise not in text
    assert text.count("\n\n") >= len(ARTICLE_PARAGRAPHS)  # paragraphs kept apart


def test_html_without_an_article_tag_uses_the_body_and_the_title_tag() -> None:
    title, text = html_to_text(
        "<html><head><title>Plain page</title></head><body><p>"
        + "word " * 100
        + "</p></body></html>"
    )
    assert title == "Plain page" and text.split()[:2] == ["word", "word"]
    assert html_to_text("") == (None, "")


def test_pdf_text_is_extracted() -> None:
    text = " ".join(ARTICLE_PARAGRAPHS[:3])
    _, extracted = pdf_to_text(make_pdf(text))
    assert "Retrieval augmented generation" in extracted and "reranking" in extracted.lower()


def test_unreadable_or_empty_pdfs_say_why() -> None:
    with pytest.raises(IngestError, match="Could not read"):
        pdf_to_text(b"%PDF-1.4 this is not really a pdf")
    with pytest.raises(IngestError, match="No readable text"):
        pdf_to_text(make_pdf("short"))


def test_youtube_transcripts_are_joined_and_failures_explain_the_fallback() -> None:
    f = fetcher(
        lambda r: httpx.Response(
            200, json={"title": "A Talk on RAG"}, headers={"content-type": "text/plain"}
        )
    )
    words = ["retrieval"] * 120
    title, text = run(youtube_to_text("dQw4w9WgXcQ", f, lambda vid: words))
    assert title == "A Talk on RAG" and text.count("retrieval") == 120

    def blocked(_: str) -> list[str]:
        raise RuntimeError("blocked")

    with pytest.raises(IngestError, match="paste the transcript"):
        run(youtube_to_text("dQw4w9WgXcQ", f, blocked))
    with pytest.raises(IngestError, match="no usable transcript"):
        run(youtube_to_text("dQw4w9WgXcQ", f, lambda vid: ["too", "short"]))


# ---- chunking ----

LONG = "\n\n".join(
    f"Paragraph {i}. " + " ".join(f"word{i}x{j}" for j in range(70)) + "." for i in range(30)
)


def test_chunks_cover_the_whole_text_and_stay_near_the_target_size() -> None:
    chunks = chunk_text(LONG, target_words=200, overlap_words=30)
    assert len(chunks) > 5
    covered = set(" ".join(chunks).split())
    assert set(LONG.split()) <= covered  # nothing lost
    assert all(len(c.split()) <= 200 + 30 + 5 for c in chunks)
    assert all(c.strip() for c in chunks)


def test_consecutive_chunks_overlap() -> None:
    chunks = chunk_text(LONG, target_words=200, overlap_words=30)
    for first, second in zip(chunks, chunks[1:], strict=False):
        assert set(first.split()[-30:]) & set(second.split()[:60])  # the seam is shared


def test_an_unpunctuated_transcript_is_still_split() -> None:
    transcript = " ".join(f"w{i}" for i in range(2000))
    chunks = chunk_text(transcript)
    assert len(chunks) >= 4 and all(len(c.split()) <= 450 + 60 for c in chunks)


def test_short_and_empty_text() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []
    assert chunk_text("just a few words here") == ["just a few words here"]


def test_default_sizes_match_the_spec_of_roughly_500_to_800_tokens() -> None:
    chunks = chunk_text(" ".join(f"word{i}" for i in range(5000)))
    tokens = [len(c.split()) * 1.33 for c in chunks[:-1]]
    assert all(500 <= t <= 800 for t in tokens)


# ---- citations ----


def test_quotes_are_checked_against_the_chunk_ignoring_case_and_punctuation() -> None:
    chunk = "Chunk size is a trade-off between recall and precision, because smaller chunks match."
    assert quote_in_chunk("chunk size is a TRADE OFF between recall and precision", chunk)
    assert not quote_in_chunk("chunk size always improves precision", chunk)
    assert not quote_in_chunk("a trade", chunk)  # too short to prove anything
    assert not quote_in_chunk("", chunk)
    assert normalize("  Hello,   World! ") == "hello world"

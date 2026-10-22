import io
import json
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from app.agent.schemas import SourceCitation, SourceNote, SourceNotes, TrackClassification
from app.config import get_settings
from app.ingest import IngestError
from app.ingest.fetch import Fetched
from app.main import create_app
from app.services.ingest import SourceSummary
from tests.conftest import TEST_DB_URL
from tests.helpers import Conv, article_html, make_pdf, seed_note

URL = "https://example.com/rag-guide"


def long_article(topics: int = 100) -> str:
    """~1800 words of distinct sentences: several chunks, so several notes."""
    paragraphs = [
        f"Technique number {i} explains that approach {i} improves retrieval quality in "
        f"measurable ways across many datasets and many different tasks."
        for i in range(topics)
    ]
    return article_html("The Big RAG Guide", paragraphs)


class StubFetcher:
    """Stands in for the network: canned pages by URL, or an error to raise."""

    def __init__(self) -> None:
        self.pages: dict[str, Fetched | Exception] = {}
        self.calls: list[str] = []

    def serve_html(self, url: str, html: str) -> None:
        self.pages[url] = Fetched(url, "text/html", html.encode())

    async def fetch(self, url: str) -> Fetched:
        self.calls.append(url)
        page = self.pages.get(url)
        if page is None:
            raise IngestError("The site answered 404.")
        if isinstance(page, Exception):
            raise page
        return page


@pytest.fixture
def stub(client: TestClient) -> StubFetcher:
    fetcher = StubFetcher()
    client.app.state.ingest.ctx.fetcher = fetcher  # type: ignore[attr-defined]
    return fetcher


def settle(client: TestClient) -> None:
    """Wait until background ingestion (including enrichment) has finished."""
    client.portal.call(client.app.state.ingest.wait_idle)  # type: ignore[union-attr,attr-defined]


def post(client: TestClient, **body: Any) -> dict[str, Any]:
    response = client.post("/api/sources", json=body)
    assert response.status_code in (200, 201), response.text
    return {**response.json(), "_status": response.status_code}


def ingest(client: TestClient, stub: StubFetcher, html: str | None = None, **extra: Any) -> str:
    stub.serve_html(URL, html or long_article())
    source = post(client, uri=URL, **extra)
    settle(client)
    return str(source["id"])


def detail(client: TestClient, source_id: str) -> dict[str, Any]:
    return client.get(f"/api/sources/{source_id}").json()


def db_exec(sql: str) -> None:
    url = make_url(TEST_DB_URL).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql)  # type: ignore[arg-type]


@pytest.fixture
def second_track() -> Iterator[None]:
    """The DSA track (a real one now) as the alternative to ai-eng; clean up what is filed in it."""
    yield
    db_exec("DELETE FROM sources")
    db_exec("DELETE FROM notes")


# ---- the happy path ----


def test_a_link_is_filed_as_cited_unconfirmed_notes_with_a_summary(
    client: TestClient, stub: StubFetcher
) -> None:
    source_id = ingest(client, stub)
    d = detail(client, source_id)

    assert d["status"] == "ready" and d["title"] == "The Big RAG Guide"
    assert d["track"] == "ai-eng" and d["error"] is None
    assert (
        d["summary"]["created"] >= 3 and d["summary"]["merged"] == 0 and d["summary"]["chunks"] >= 3
    )
    assert d["headline"].startswith(f"Filed {d['summary']['created']} notes under AI Engineering")
    assert d["headline"].endswith(f"linked {d['summary']['linked']}.")

    page_text = " ".join(c for c in ["".join(article_html and long_article().split("<p>"))]).lower()
    for item in d["items"]:
        assert (
            item["action"] == "created"
            and item["origin"] == "source"
            and item["confirmed"] is False
        )
        assert item["citations"], "every filed note cites its source"
        for cite in item["citations"]:
            assert (
                cite["quote"].lower().split()[0] in page_text
            )  # taken from the page, not invented

    notes = client.get("/api/notes?track=ai-eng").json()
    assert len(notes) == d["summary"]["created"]
    assert all(n["origin"] == "source" and n["confirmed"] is False for n in notes)


def test_enrichment_adds_diagrams_and_practice_questions_but_quizzes_wait_for_approval(
    client: TestClient, stub: StubFetcher
) -> None:
    source_id = ingest(client, stub)
    notes = client.get("/api/notes?track=ai-eng").json()
    assert all(client.get(f"/api/notes/{n['id']}/diagram").status_code == 200 for n in notes)

    # Review items exist, but nothing from an unapproved source is quizzed yet.
    assert client.get("/api/reviews/due").json()["total_due"] == 0
    client.post(f"/api/sources/{source_id}/approve")
    assert client.get("/api/reviews/due").json()["total_due"] >= len(notes)


def test_approving_confirms_the_notes_once(client: TestClient, stub: StubFetcher) -> None:
    source_id = ingest(client, stub)
    approved = client.post(f"/api/sources/{source_id}/approve").json()
    assert approved["status"] == "approved"
    assert all(n["confirmed"] for n in client.get("/api/notes?track=ai-eng").json())
    assert client.post(f"/api/sources/{source_id}/approve").status_code == 409


def test_undoing_one_item_removes_only_that_note_and_approval_skips_it(
    client: TestClient, stub: StubFetcher
) -> None:
    source_id = ingest(client, stub)
    before = detail(client, source_id)
    victim = before["items"][0]
    assert client.post(f"/api/capture-events/{victim['event_id']}/undo").json()["undone"] is True

    after = detail(client, source_id)
    assert after["summary"]["created"] == before["summary"]["created"] - 1
    # A created note is deleted, and its capture event goes with it, so the item disappears.
    assert victim["event_id"] not in [i["event_id"] for i in after["items"]]
    client.post(f"/api/sources/{source_id}/approve")
    titles = {n["title"] for n in client.get("/api/notes?track=ai-eng").json()}
    assert victim["title"] not in titles and len(titles) == before["summary"]["created"] - 1


def test_the_same_link_twice_is_not_ingested_twice(client: TestClient, stub: StubFetcher) -> None:
    source_id = ingest(client, stub)
    notes_before = len(client.get("/api/notes").json())
    again = post(client, uri=URL + "/?utm_source=newsletter#intro")
    assert again["_status"] == 200 and again["deduplicated"] is True and again["id"] == source_id
    settle(client)
    assert len(stub.calls) == 1
    assert len(client.get("/api/notes").json()) == notes_before
    assert len(client.get("/api/sources").json()) == 1


def test_material_that_overlaps_a_note_you_already_have_is_merged_not_duplicated(
    client: TestClient, stub: StubFetcher
) -> None:
    # The page's heading runs into its first paragraph in the extracted text, so the first
    # "sentence" of chunk 0 starts with the heading.
    sentence = "The Big RAG Guide Technique number 0 explains that approach 0 improves retrieval quality in measurable ways across many datasets and many different tasks"
    title = sentence[:80].rstrip()  # the fake extractor titles a note with the first 80 characters
    seed_note(title, sentence + ".")
    source_id = ingest(client, stub)
    d = detail(client, source_id)
    merged = [i for i in d["items"] if i["action"] == "merged"]
    assert len(merged) == 1 and merged[0]["origin"] == "user"  # the learner's note stays theirs
    assert merged[0]["citations"] and merged[0]["before_body_md"]
    assert d["summary"]["merged"] == 1
    assert "merged 1 into existing notes" in d["headline"]
    assert len([n for n in client.get("/api/notes").json() if n["title"] == title]) == 1


# ---- citations are verified, never trusted ----


class OverrideLLM:
    """Wraps the fake LLM, answering selected schemas with canned output."""

    def __init__(self, inner: Any, overrides: dict[type, Any]) -> None:
        self.inner, self.overrides, self.calls = inner, overrides, []

    async def complete_structured(self, kind: Any, *, schema: type, **kw: Any) -> Any:
        self.calls.append(schema)
        override = self.overrides.get(schema)
        if override is not None:
            return override() if callable(override) else override
        return await self.inner.complete_structured(kind, schema=schema, **kw)

    def stream_text(self, *a: Any, **kw: Any) -> Any:
        return self.inner.stream_text(*a, **kw)


def swap_llm(client: TestClient, overrides: dict[type, Any]) -> OverrideLLM:
    deps = client.app.state.deps  # type: ignore[attr-defined]
    llm = OverrideLLM(deps.llm, overrides)
    deps.llm = llm
    return llm


def test_notes_with_fabricated_or_missing_citations_are_dropped(
    client: TestClient, stub: StubFetcher
) -> None:
    html = article_html(
        "Short",
        [
            " ".join(f"filler{i}" for i in range(150))
            + " Real quoted sentence about embeddings appears right here in the text. "
            + " ".join(f"tail{i}" for i in range(60))
        ],
    )
    swap_llm(
        client,
        {
            SourceNotes: SourceNotes(
                notes=[
                    SourceNote(
                        title="Grounded claim",
                        body_md="Embeddings appear in the text.",
                        citations=[
                            SourceCitation(
                                chunk=0,
                                quote="real quoted sentence about embeddings appears right here",
                            )
                        ],
                    ),
                    SourceNote(
                        title="Invented claim",
                        body_md="Something the page never says.",
                        citations=[
                            SourceCitation(
                                chunk=0, quote="the page definitely states this invented fact"
                            )
                        ],
                    ),
                    SourceNote(title="Uncited claim", body_md="No citation at all.", citations=[]),
                    SourceNote(
                        title="Wrong chunk claim",
                        body_md="Cites a chunk that was not shown.",
                        citations=[
                            SourceCitation(
                                chunk=99,
                                quote="real quoted sentence about embeddings appears right here",
                            )
                        ],
                    ),
                ]
            )
        },
    )
    d = detail(client, ingest(client, stub, html))
    assert [i["title"] for i in d["items"]] == ["Grounded claim"]
    assert d["items"][0]["citations"][0]["chunk_idx"] == 0


# ---- classification and the "which track?" question ----


def test_with_several_tracks_and_no_hint_the_model_classifies_once(
    client: TestClient, stub: StubFetcher
) -> None:
    llm = swap_llm(client, {})
    d = detail(client, ingest(client, stub))
    assert d["status"] == "ready" and d["track"] == "ai-eng"  # the fake picks the first listed
    assert llm.calls.count(TrackClassification) == 1


def test_a_track_hint_skips_classification(
    client: TestClient, stub: StubFetcher, second_track: None
) -> None:
    llm = swap_llm(client, {})
    d = detail(client, ingest(client, stub, track_hint="dsa"))
    assert d["track"] == "dsa" and d["status"] == "ready"
    assert TrackClassification not in llm.calls


def test_an_unknown_track_hint_is_rejected(client: TestClient, stub: StubFetcher) -> None:
    assert client.post("/api/sources", json={"uri": URL, "track_hint": "nope"}).status_code == 404


def test_confident_classification_files_straight_into_the_right_track(
    client: TestClient, stub: StubFetcher, second_track: None
) -> None:
    swap_llm(
        client,
        {TrackClassification: TrackClassification(track="dsa", topic="graphs", confidence=0.93)},
    )
    d = detail(client, ingest(client, stub))
    assert d["status"] == "ready" and d["track"] == "dsa" and d["topic"] == "graphs"


def test_low_confidence_asks_which_track_then_resumes_from_where_it_stopped(
    client: TestClient, stub: StubFetcher, second_track: None
) -> None:
    llm = swap_llm(
        client,
        {
            TrackClassification: TrackClassification(
                track="ai-eng", topic="maybe rag", confidence=0.3
            )
        },
    )
    source_id = ingest(client, stub)
    d = detail(client, source_id)
    assert d["status"] == "needs_track" and d["suggested_track"] == "ai-eng"
    assert d["track_confidence"] == pytest.approx(0.3) and d["items"] == []
    assert client.get("/api/notes").json() == []  # nothing filed until the user answers

    assert client.post(f"/api/sources/{source_id}/track", json={"track": "nope"}).status_code == 404
    chosen = client.post(f"/api/sources/{source_id}/track", json={"track": "dsa"})
    assert chosen.status_code == 200
    settle(client)
    d = detail(client, source_id)
    assert d["status"] == "ready" and d["track"] == "dsa" and d["items"]
    assert llm.calls.count(TrackClassification) == 1  # it was not asked again
    assert len(stub.calls) == 1  # and the page was not fetched again
    assert client.post(f"/api/sources/{source_id}/track", json={"track": "dsa"}).status_code == 409


def test_an_unknown_track_from_the_model_counts_as_low_confidence(
    client: TestClient, stub: StubFetcher, second_track: None
) -> None:
    swap_llm(
        client,
        {TrackClassification: TrackClassification(track="invented", topic="x", confidence=0.99)},
    )
    d = detail(client, ingest(client, stub))
    assert d["status"] == "needs_track" and d["suggested_track"] is None


# ---- failures ----


def test_a_failed_fetch_is_reported_and_can_be_retried(
    client: TestClient, stub: StubFetcher
) -> None:
    stub.pages[URL] = IngestError("The site took too long to answer.")
    source = post(client, uri=URL)
    settle(client)
    d = detail(client, source["id"])
    assert d["status"] == "failed" and d["error"] == "The site took too long to answer."
    assert client.get("/api/notes").json() == []

    stub.serve_html(URL, long_article())
    assert client.post(f"/api/sources/{source['id']}/retry").status_code == 200
    settle(client)
    assert detail(client, source["id"])["status"] == "ready"
    assert client.post(f"/api/sources/{source['id']}/retry").status_code == 409


def test_submitting_a_failed_link_again_retries_it_instead_of_duplicating(
    client: TestClient, stub: StubFetcher
) -> None:
    stub.pages[URL] = IngestError("The site answered 500.")
    first = post(client, uri=URL)
    settle(client)
    stub.serve_html(URL, long_article())
    second = post(client, uri=URL)
    assert second["id"] == first["id"] and second["deduplicated"] is False
    settle(client)
    assert detail(client, first["id"])["status"] == "ready"
    assert len(client.get("/api/sources").json()) == 1


def test_a_page_with_no_real_text_fails_clearly(client: TestClient, stub: StubFetcher) -> None:
    stub.serve_html(URL, "<html><body><p>Too little.</p></body></html>")
    source = post(client, uri=URL)
    settle(client)
    d = detail(client, source["id"])
    assert d["status"] == "failed" and "Not enough readable text" in d["error"]


def test_the_server_refuses_to_fetch_private_addresses_through_the_api(client: TestClient) -> None:
    source = post(client, uri="http://127.0.0.1:80/api/notes")  # real SafeFetcher, no stub
    settle(client)
    d = detail(client, source["id"])
    assert d["status"] == "failed" and "not a public website" in d["error"]
    assert client.get("/api/notes").json() == []


def test_garbage_links_are_rejected_up_front(client: TestClient) -> None:
    for bad in ({"uri": "javascript:alert(1)"}, {"uri": "ftp://x.org/f"}, {}):
        assert client.post("/api/sources", json=bad).status_code == 422


# ---- other kinds ----


def test_pasted_text_is_filed_and_deduplicated_by_content(client: TestClient) -> None:
    text = " ".join(
        f"Sentence {i} explains how technique {i} improves recall in practice for real systems."
        for i in range(40)
    )
    first = post(client, text=text, title="My pasted notes")
    settle(client)
    d = detail(client, first["id"])
    assert (
        d["status"] == "ready"
        and d["kind"] == "text"
        and d["title"] == "My pasted notes"
        and d["items"]
    )
    again = post(client, text=text)
    assert again["_status"] == 200 and again["id"] == first["id"]
    assert client.post("/api/sources", json={"text": "far too short"}).status_code == 422


def test_a_pdf_upload_is_filed_and_the_same_file_is_not_filed_twice(client: TestClient) -> None:
    pdf = make_pdf(
        " ".join(
            f"Paper section {i} argues that method {i} reduces error rates considerably in benchmarks."
            for i in range(45)
        )
    )
    files = {"file": ("paper.pdf", io.BytesIO(pdf), "application/pdf")}
    first = client.post("/api/sources/upload", files=files)
    assert first.status_code == 201 and first.json()["kind"] == "pdf"
    settle(client)
    assert detail(client, first.json()["id"])["status"] == "ready"

    again = client.post(
        "/api/sources/upload", files={"file": ("copy.pdf", io.BytesIO(pdf), "application/pdf")}
    )
    assert again.status_code == 200 and again.json()["deduplicated"] is True
    assert again.json()["id"] == first.json()["id"]


def test_uploads_must_be_real_readable_pdfs(client: TestClient) -> None:
    not_pdf = client.post(
        "/api/sources/upload", files={"file": ("x.pdf", io.BytesIO(b"hello"), "application/pdf")}
    )
    assert not_pdf.status_code == 415
    scanned = client.post(
        "/api/sources/upload",
        files={"file": ("s.pdf", io.BytesIO(make_pdf("tiny")), "application/pdf")},
    )
    assert scanned.status_code == 422 and "No readable text" in scanned.json()["detail"]
    unknown = client.post(
        "/api/sources/upload",
        data={"track_hint": "nope"},
        files={"file": ("a.pdf", io.BytesIO(make_pdf("x")), "application/pdf")},
    )
    assert unknown.status_code == 404


def test_a_youtube_link_is_filed_from_its_transcript(
    client: TestClient, stub: StubFetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    transcript = [
        f"In this talk we explain why idea {i} matters for retrieval systems in production."
        for i in range(80)
    ]
    monkeypatch.setattr("app.ingest.extract._default_transcript", lambda video_id: transcript)
    stub.pages[
        "https://www.youtube.com/oembed?format=json&url=https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    ] = Fetched("x", "text/plain", json.dumps({"title": "RAG Explained"}).encode())
    source = post(client, uri="https://youtu.be/dQw4w9WgXcQ?si=abc")
    settle(client)
    d = detail(client, source["id"])
    assert (
        d["kind"] == "youtube"
        and d["title"] == "RAG Explained"
        and d["status"] == "ready"
        and d["items"]
    )
    assert d["uri"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_a_youtube_link_without_a_transcript_explains_the_fallback(
    client: TestClient, stub: StubFetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    def blocked(video_id: str) -> list[str]:
        raise RuntimeError("blocked")

    monkeypatch.setattr("app.ingest.extract._default_transcript", blocked)
    source = post(client, uri="https://youtu.be/dQw4w9WgXcQ")
    settle(client)
    assert "paste the transcript" in detail(client, source["id"])["error"]


# ---- restart recovery ----


def test_unfinished_sources_resume_after_a_restart() -> None:
    text = " ".join(
        f"Point {i} says that technique {i} improves retrieval quality across datasets."
        for i in range(60)
    )
    db_exec("TRUNCATE capture_events, notes, sources CASCADE")
    db_exec(
        "INSERT INTO sources (user_id, kind, uri, title, status, raw_text) VALUES "
        f"('00000000-0000-0000-0000-000000000001', 'text', 'sha256:restart', 'Interrupted', 'processing', '{text}')"
    )
    with TestClient(create_app()) as client:  # startup resumes it
        settle(client)
        source = client.get("/api/sources").json()[0]
        assert source["status"] == "ready" and source["title"] == "Interrupted"
        assert client.get(f"/api/sources/{source['id']}").json()["items"]


# ---- n8n: shared secret instead of a session ----


@pytest.fixture
def secured(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    for key, value in {
        "AUTH_PASSPHRASE": "correct horse battery staple",
        "SESSION_SECRET": "s" * 40,
        "RECALL_SHARED_SECRET": "n8n-shared-secret-0123456789",
        "CORS_ORIGINS": '["http://localhost:3000"]',
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        with TestClient(create_app(), base_url="http://localhost:3000") as client:
            yield client
    finally:
        get_settings.cache_clear()


def test_n8n_can_call_the_ingest_and_export_endpoints_with_the_shared_secret(
    secured: TestClient,
) -> None:
    text = " ".join(
        f"Item {i} states that practice {i} improves recall in real systems." for i in range(40)
    )
    good = {"X-Recall-Secret": "n8n-shared-secret-0123456789"}
    assert secured.post("/api/sources", json={"text": text}).status_code == 401
    assert (
        secured.post(
            "/api/sources", json={"text": text}, headers={"X-Recall-Secret": "wrong"}
        ).status_code
        == 401
    )
    assert secured.post("/api/sources", json={"text": text}, headers=good).status_code == 201
    assert secured.get("/api/export", headers=good).status_code == 200
    assert secured.get("/api/sources").status_code == 401


def test_the_shared_secret_opens_nothing_else(secured: TestClient) -> None:
    good = {"X-Recall-Secret": "n8n-shared-secret-0123456789"}
    for path in ("/api/notes", "/api/graph", "/api/reviews/due", "/api/tracks"):
        assert secured.get(path, headers=good).status_code == 401, path


def test_a_weak_shared_secret_refuses_to_start() -> None:
    from pydantic import ValidationError

    from app.config import Settings

    for weak in ("change-me", "short"):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, recall_shared_secret=weak)  # type: ignore[call-arg]
    assert Settings(_env_file=None, recall_shared_secret="").recall_shared_secret == ""  # type: ignore[call-arg]


# ---- export ----


def test_export_writes_markdown_with_citations_links_and_diagrams(
    client: TestClient, stub: StubFetcher
) -> None:
    ingest(client, stub)
    files = client.get("/api/export").json()["files"]
    assert files and all(
        f["path"].startswith("ai-eng/") and f["path"].endswith(".md") for f in files
    )
    body = files[0]["content"]
    assert (
        body.startswith('---\ntitle: "') and "origin: source" in body and "confirmed: false" in body
    )
    assert "## Sources" in body and "chunk " in body
    assert any("```mermaid" in f["content"] for f in files)


# ---- summary wording ----


def test_the_headline_reads_like_the_spec_example() -> None:
    assert (
        SourceSummary(7, 2, 4, 9).headline("AI Eng")
        == "Filed 7 notes under AI Eng, merged 2 into existing notes, linked 4."
    )
    assert SourceSummary(1, 0, 0, 1).headline(None) == "Filed 1 note."
    assert (
        SourceSummary(0, 0, 0, 3).headline("AI Eng")
        == "Nothing worth filing was found in this source."
    )


# ---- ingest_review by voice ----


def test_voice_review_summarises_then_approves(client: TestClient, stub: StubFetcher) -> None:
    source_id = ingest(client, stub)
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.say("what did you file?")
        conv.kind("mode", mode="ingest_review")
        conv.kind("assistant_done")
        spoken = conv.spoken()
        assert "Filed" in spoken and "Shall I keep them" in spoken and "The Big RAG Guide" in spoken

        conv.say("yes, looks good")
        conv.kind("mode", mode="capture")
        conv.kind("assistant_done")
        assert "I confirmed" in conv.spoken()
    assert detail(client, source_id)["status"] == "approved"
    assert all(n["confirmed"] for n in client.get("/api/notes").json())


def test_voice_review_can_discard_everything(client: TestClient, stub: StubFetcher) -> None:
    source_id = ingest(client, stub)
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.say("what's new")
        conv.kind("mode", mode="ingest_review")
        conv.kind("assistant_done")  # let the summary finish before answering it
        conv.say("no, remove them")
        conv.kind("mode", mode="capture")
        conv.kind("assistant_done")
        assert "removed everything" in conv.spoken()
    assert client.get("/api/notes").json() == []
    assert detail(client, source_id)["status"] == "approved"


def test_voice_review_not_now_leaves_it_waiting_and_nothing_new_is_handled(
    client: TestClient, stub: StubFetcher
) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.say("what did you file")
        conv.kind("assistant_done")
        assert "Nothing new is waiting" in conv.spoken()

    source_id = ingest(client, stub)
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.say("review the new material")
        conv.kind("mode", mode="ingest_review")
        conv.kind("assistant_done")
        conv.say("not now")
        conv.kind("mode", mode="capture")
    assert detail(client, source_id)["status"] == "ready"

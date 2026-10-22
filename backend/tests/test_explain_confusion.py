from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from tests.conftest import TEST_DB_URL
from tests.helpers import Conv, seed_note

RAG_TITLE = "Retrieval augmented generation fetches documents first"
RAG_BODY = "Retrieval augmented generation fetches documents before the model answers."


def confusion_rows() -> list[tuple[str, str | None]]:
    import psycopg
    from sqlalchemy.engine import make_url

    url = make_url(TEST_DB_URL).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(url) as conn:
        return [(r[0], r[1]) for r in conn.execute(text_sql())]


def text_sql() -> str:
    return "SELECT trigger, note_id::text FROM confusion_events ORDER BY created_at"


# ---- explain ----


def test_explaining_speaks_what_how_why_impact_and_shows_a_diagram(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.say("Explain retrieval augmented generation")
        event = conv.kind("explain")
        assert event["topic"] == "retrieval augmented generation" and event["simple"] is False
        assert event["diagram"]["kind"] == "mermaid"
        assert event["diagram"]["source"].startswith("flowchart TD")
        spoken = conv.spoken()
        for beat in ("what it is", "how it works", "matters", "impact"):
            assert beat in spoken
        assert "**" not in spoken and "#" not in spoken  # nothing markdown to read aloud

    # Explaining is not capturing: the assistant's words are never filed as the learner's notes.
    assert client.get("/api/notes?track=ai-eng").json() == []


def test_an_explanation_is_grounded_on_the_learners_own_note(client: TestClient) -> None:
    note_id, _ = seed_note(RAG_TITLE, RAG_BODY)
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.say("What is retrieval augmented generation")
        assert conv.kind("explain")["note_id"] == str(note_id)


def test_saving_an_explanation_makes_an_unconfirmed_assistant_note(client: TestClient) -> None:
    saved = client.post(
        "/api/notes",
        json={"title": "RAG, explained", "body_md": "It fetches first.", "origin": "assistant"},
    ).json()
    assert saved["origin"] == "assistant" and saved["confirmed"] is False
    confirmed = client.patch(f"/api/notes/{saved['id']}", json={"confirmed": True}).json()
    assert confirmed["confirmed"] is True and confirmed["origin"] == "assistant"


# ---- confusion ----


def test_i_dont_get_it_logs_marks_fragile_and_re_explains_simply_with_a_diagram(
    client: TestClient,
) -> None:
    note_id, _ = seed_note(RAG_TITLE, RAG_BODY)
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.say("Explain retrieval augmented generation")
        first = conv.kind("explain")
        assert first["simple"] is False

        conv.say("I don't get it")
        confusion = conv.kind("confusion")
        assert confusion["trigger"].startswith("phrase:") and confusion["note_id"] == str(note_id)
        again = conv.kind("explain", simple=True)
        assert again["diagram"] is not None  # the simplified version still comes with a diagram
        assert "slowly" in again["text"].lower()
        assert not conv.of("notes")  # a confused turn is not captured as a note

    assert confusion_rows() == [(confusion["trigger"], str(note_id))]
    node = client.get("/api/graph?track=ai-eng").json()["nodes"][0]
    assert node["fragile"] is True


def test_asking_the_same_question_twice_counts_as_confusion(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.say("How does reranking work?")
        conv.kind("explain", simple=False)
        conv.say("how does reranking work")
        assert conv.kind("confusion")["trigger"] == "repeated question"
        conv.kind("explain", simple=True)


def test_a_different_question_is_not_confusion(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.say("How does reranking work?")
        conv.kind("explain", simple=False)
        conv.say("Why does chunk size matter?")
        conv.kind("explain", simple=False)
        assert not conv.of("confusion")


@pytest.fixture
def silence_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("CONFUSION_SILENCE_S", "0.4")
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            yield client
    finally:
        get_settings.cache_clear()


def test_a_long_silence_after_an_explanation_counts_as_confusion(
    silence_client: TestClient,
) -> None:
    with silence_client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.say("Explain retrieval augmented generation")
        assert conv.kind("explain", simple=False)
        # ... and then the learner says nothing.
        assert conv.kind("confusion")["trigger"] == "silence after explanation"
        assert conv.kind("explain", simple=True)


def test_replying_in_time_cancels_the_silence_follow_up(silence_client: TestClient) -> None:
    with silence_client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.say("Explain retrieval augmented generation")
        conv.kind("explain", simple=False)
        conv.say("Got it, retrieval comes before generation.")  # a prompt reply
        conv.kind("notes")
        import time

        time.sleep(0.8)  # longer than the silence window
        assert not conv.of("confusion")

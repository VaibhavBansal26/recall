import json

from fastapi.testclient import TestClient


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "up", "voice_provider": "fake"}


def test_ai_eng_track_is_synced_from_yaml(client: TestClient) -> None:
    slugs = [t["slug"] for t in client.get("/api/tracks").json()]
    assert slugs == ["ai-eng"]


def test_create_and_fetch_session(client: TestClient) -> None:
    created = client.post("/api/sessions", json={"track": "ai-eng"})
    assert created.status_code == 201
    body = client.get(f"/api/sessions/{created.json()['id']}").json()
    assert body["track"] == "ai-eng"
    assert body["utterances"] == []


def test_unknown_track_is_404(client: TestClient) -> None:
    assert client.post("/api/sessions", json={"track": "nope"}).status_code == 404


def test_typed_message_over_ws_is_stored(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        ws.send_text(json.dumps({"type": "start", "track": "ai-eng"}))
        started = ws.receive_json()
        assert started["type"] == "session"

        ws.send_text(json.dumps({"type": "text", "text": "RAG retrieves context first"}))
        events = []
        while not any(e["type"] in ("assistant_done", "latency") for e in events[-1:]):
            events.append(ws.receive_json())

    kinds = [e["type"] for e in events]
    assert kinds[0] == "utterance" and events[0]["speaker"] == "user"
    assert "assistant_delta" in kinds and "audio" in kinds

    detail = client.get(f"/api/sessions/{started['session_id']}").json()
    assert [(u["speaker"], u["text"]) for u in detail["utterances"]] == [
        ("user", "RAG retrieves context first"),
        ("assistant", "Got it, noted. Keep going."),
    ]


def test_text_before_start_is_an_error(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        ws.send_text(json.dumps({"type": "text", "text": "hi"}))
        assert ws.receive_json()["type"] == "error"


def test_invalid_event_is_an_error_not_a_crash(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        ws.send_text("not json")
        assert ws.receive_json()["type"] == "error"

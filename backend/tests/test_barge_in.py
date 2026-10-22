import json
from typing import Any

from fastapi.testclient import TestClient

from app.voice.barge_in import BargeInDetector


def test_detector_ignores_user_when_assistant_is_silent() -> None:
    d = BargeInDetector()
    assert not d.should_interrupt(assistant_speaking=False, speech_started=True)
    assert not d.should_interrupt(assistant_speaking=False, partial_text="hello there")


def test_detector_interrupts_on_vad_hint_or_enough_words() -> None:
    d = BargeInDetector(min_words=2)
    assert d.should_interrupt(assistant_speaking=True, speech_started=True)
    assert d.should_interrupt(assistant_speaking=True, partial_text="wait what")
    assert not d.should_interrupt(assistant_speaking=True, partial_text="uh")
    assert not d.should_interrupt(assistant_speaking=True)


def _recv_until(ws: Any, kind: str) -> list[dict[str, Any]]:
    seen = []
    while True:
        ev = ws.receive_json()
        seen.append(ev)
        if ev["type"] == kind:
            return seen


def test_speech_start_cancels_the_reply_and_keeps_the_partial_turn(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        ws.send_text(json.dumps({"type": "start", "track": "ai-eng"}))
        session_id = ws.receive_json()["session_id"]
        ws.send_text(json.dumps({"type": "text", "text": "Embeddings map text to vectors"}))

        _recv_until(ws, "assistant_delta")  # first spoken sentence is out, second is pending
        ws.send_text(json.dumps({"type": "speech_start"}))
        events = _recv_until(ws, "interrupted")
        partial = next(e for e in [ws.receive_json()] if e["type"] == "utterance")
        assert partial["interrupted"] is True and partial["speaker"] == "assistant"
        assert not any(e["type"] == "assistant_done" for e in events)

    detail = client.get(f"/api/sessions/{session_id}").json()
    assistant = [u for u in detail["utterances"] if u["speaker"] == "assistant"]
    assert [(u["text"], u["interrupted"]) for u in assistant] == [("Got it, noted.", True)]

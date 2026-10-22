import time
from typing import Any

from fastapi.testclient import TestClient

from app.db.models import LinkKind, NoteOrigin, PromptKind
from app.services import links as links_svc
from tests.helpers import Conv, run_db, seed_note


def seed_notes() -> dict[str, str]:
    """'Embeddings basics' is a prerequisite of 'Vector search'; only the latter has a question."""
    basics, _ = seed_note("Embeddings basics", "Embeddings map text to vectors.")
    search, _ = seed_note(
        "Vector search finds nearest embeddings",
        "Vector search finds the nearest embeddings to a query.",
        [("What does vector search find?", "nearest embeddings", PromptKind.question)],
    )

    async def link(db: Any, track: Any) -> None:
        await links_svc.create_link(
            db,
            from_note_id=basics,
            to_note_id=search,
            kind=LinkKind.prerequisite,
            origin=NoteOrigin.user,
        )

    run_db(link)
    return {"basics": str(basics), "search": str(search)}


def test_notes_are_read_in_learning_order_with_pace_controls_then_a_question(
    client: TestClient,
) -> None:
    ids = seed_notes()
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.say("Read me my notes on embeddings")

        conv.kind("mode", mode="read_back")
        first = conv.kind("read_back", index=0)
        assert first["total"] == 2 and first["title"] == "Embeddings basics"  # prerequisite first
        assert first["why"] and first["finished"] is False
        assert conv.kind("diagram")["items"][0]["note_id"] == ids["basics"]  # a diagram with it
        conv.kind("assistant_done")
        assert "Note 1 of 2" in conv.spoken() and "Say next to continue" in conv.spoken()

        conv.say("slower")
        slower = conv.kind("read_back", speed=0.85)
        assert slower["index"] == 0  # same note again, at the new pace

        conv.say("repeat")
        assert conv.kind("read_back", index=0)["speed"] == 0.85

        conv.say("next")
        last = conv.kind("read_back", index=1)
        assert (
            last["title"] == "Vector search finds nearest embeddings" and last["finished"] is True
        )
        # It ends with one question, which hands over to the quiz.
        conv.kind("mode", mode="recall_quiz")
        asking = conv.kind("quiz", phase="asking")
        assert asking["prompt"] == "What does vector search find?"
        conv.kind("assistant_done")
        assert "last one" in conv.spoken()


def test_skip_stop_and_faster_work(client: TestClient) -> None:
    seed_notes()
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.say("read me my notes on embeddings")
        conv.kind("read_back", index=0)

        conv.say("faster")
        assert conv.kind("read_back", speed=1.15)["index"] == 0

        conv.say("stop")
        stopped = conv.kind("read_back", finished=True)
        assert stopped["note_id"] is None
        conv.kind("mode", mode="capture")


def test_reading_back_with_no_matching_notes_says_so(client: TestClient) -> None:
    seed_notes()
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.say("read me my notes on zebras")
        conv.kind("assistant_done")
        assert "don't have any notes about zebras" in conv.spoken()
        assert not conv.of("read_back")


def test_capture_creates_a_few_review_items_without_leaking_answers(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.say(
            "Reranking reorders retrieved chunks by relevance. "
            "Chunk size trades recall for precision."
        )
        conv.kind("notes")
        conv.kind("diagram")

        deadline = time.time() + 5
        items: list[dict[str, Any]] = []
        while time.time() < deadline:
            items = client.get("/api/reviews/due?track=ai-eng").json()["items"]
            if len(items) >= 4:
                break
            time.sleep(0.2)

    # Two notes, one cloze and one question each (the per-note cap), all due immediately.
    assert len(items) == 4
    by_note: dict[str, list[str]] = {}
    for item in items:
        by_note.setdefault(item["note_id"], []).append(item["kind"])
        assert "answer" not in item
        if item["kind"] == "cloze":
            assert item["prompt"].count("_____") == 1
    assert all(sorted(kinds) == ["cloze", "question"] for kinds in by_note.values())


def test_a_repeat_capture_does_not_pile_up_more_items_for_the_same_note(
    client: TestClient,
) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        for _ in range(2):
            conv.say("Embeddings map text into vectors for similarity search.")
            conv.kind("assistant_done")
            conv.kind("diagram")
            time.sleep(0.8)
    count = client.get("/api/reviews/due?track=ai-eng").json()["total_due"]
    assert count == 2

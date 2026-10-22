from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from app.db.models import PromptKind
from tests.helpers import Conv, seed_note

PROMPT = "What does RAG do before generating?"
ANSWER = "retrieves context"
BODY = "RAG retrieves context before generation."


def seed() -> tuple[str, str]:
    note_id, (item_id,) = seed_note(
        "RAG retrieves context first", BODY, [(PROMPT, ANSWER, PromptKind.question)]
    )
    return str(note_id), str(item_id)


def open_quiz(ws: Any, **extra: Any) -> Conv:
    conv = Conv(ws)
    conv.start()
    conv.send(type="quiz", **extra)
    return conv


def test_a_correct_unaided_answer_is_graded_and_leaves_the_queue(client: TestClient) -> None:
    _, item_id = seed()
    with client.websocket_connect("/ws/voice") as ws:
        conv = open_quiz(ws)
        asking = conv.kind("quiz", phase="asking")
        assert asking["prompt"] == PROMPT and asking["position"] == 1 and asking["total"] == 1
        assert "answer" not in asking or asking["answer"] is None  # never leaked before answering

        conv.say("It retrieves context first, I think")
        graded = conv.kind("quiz", phase="graded")
        assert graded["tier"] == 0 and graded["grade"] in ("Good", "Easy")
        assert graded["answer"] == ANSWER and graded["fragile"] is False
        ended = conv.kind("quiz", phase="ended")
        assert ended["summary"] == {
            "total": 1,
            "unaided": 1,
            "hinted": 0,
            "revealed": 0,
            "fragile": 0,
        }
        conv.kind("mode", mode="capture")
        conv.kind("assistant_done")
        assert PROMPT in conv.spoken()

    due = client.get("/api/reviews/due?track=ai-eng").json()
    assert due["total_due"] == 0 and item_id not in [i["id"] for i in due["items"]]
    assert due["next_due_at"] is not None


def test_wrong_answers_climb_the_ladder_to_a_full_reveal_graded_again(client: TestClient) -> None:
    note_id, _ = seed()
    with client.websocket_connect("/ws/voice") as ws:
        conv = open_quiz(ws)
        conv.kind("quiz", phase="asking")

        conv.say("Something about databases")
        t1 = conv.kind("quiz", phase="hint", tier=1)
        assert "RAG retrieves context first" in t1["hint"] and t1["answer"] is None  # a nudge

        conv.say("Maybe vectors")
        t2 = conv.kind("quiz", phase="hint", tier=2)
        assert t2["hint"].startswith("It starts like this") and t2["answer"] is None

        conv.say("No clue at all")
        t3 = conv.kind("quiz", phase="hint", tier=3)
        assert t3["answer"] == ANSWER  # the reveal
        diagram = conv.kind("diagram")  # the reveal comes with a diagram
        assert diagram["items"][0]["note_id"] == note_id

        conv.say("okay I see")  # the follow-up after the reveal
        graded = conv.kind("quiz", phase="graded")
        assert graded["tier"] == 3 and graded["grade"] == "Again"
        conv.kind("quiz", phase="ended")

    # Tier 3 once: scheduled soon but not yet fragile.
    graph = client.get("/api/graph?track=ai-eng").json()
    assert [n["fragile"] for n in graph["nodes"]] == [False]


def test_forgetting_walks_the_same_ladder_and_hint_tiers_are_logged(client: TestClient) -> None:
    seed()
    with client.websocket_connect("/ws/voice") as ws:
        conv = open_quiz(ws)
        conv.kind("quiz", phase="asking")
        for tier in (1, 2, 3):
            conv.say("I forgot")
            conv.kind("quiz", phase="hint", tier=tier)
        conv.say("thanks")
        graded = conv.kind("quiz", phase="graded")
        assert graded["tier"] == 3


def test_a_nudge_that_works_is_graded_hard(client: TestClient) -> None:
    seed()
    with client.websocket_connect("/ws/voice") as ws:
        conv = open_quiz(ws)
        conv.kind("quiz", phase="asking")
        conv.say("I have no idea")
        conv.kind("quiz", phase="hint", tier=1)
        conv.say("oh, it retrieves context")
        graded = conv.kind("quiz", phase="graded")
        assert graded["tier"] == 1 and graded["grade"] == "Hard"


def test_tier_three_twice_in_a_row_sets_fragile_and_pulls_the_review_in(
    client: TestClient,
) -> None:
    note_id, _ = seed()
    for round_number in (1, 2):
        with client.websocket_connect("/ws/voice") as ws:
            conv = Conv(ws)
            conv.start()
            conv.send(type="quiz", note_id=note_id)  # practice on this note, due or not
            conv.kind("quiz", phase="asking")
            for _ in range(3):
                conv.say("I forgot")
            conv.kind("quiz", phase="hint", tier=3)
            conv.say("ok")
            graded = conv.kind("quiz", phase="graded")
            assert graded["fragile"] is (round_number == 2)
            if round_number == 2:
                due = datetime.fromisoformat(graded["next_due"])
                assert due <= datetime.now(UTC) + timedelta(days=1, minutes=1)

    node = client.get("/api/graph?track=ai-eng").json()["nodes"][0]
    assert node["fragile"] is True
    assert node["strength"] is not None  # has review history now


def test_buttons_do_what_the_spoken_commands_do(client: TestClient) -> None:
    seed()
    with client.websocket_connect("/ws/voice") as ws:
        conv = open_quiz(ws)
        conv.kind("quiz", phase="asking")
        conv.send(type="quiz_action", action="hint")
        conv.kind("quiz", phase="hint", tier=1)
        conv.send(type="quiz_action", action="end")
        ended = conv.kind("quiz", phase="ended")
        assert ended["summary"]["total"] == 0
        conv.kind("assistant_done")
        assert "didn't get to any questions" in conv.spoken()


def test_skipping_does_not_grade_and_the_item_stays_due(client: TestClient) -> None:
    _, item_id = seed()
    with client.websocket_connect("/ws/voice") as ws:
        conv = open_quiz(ws)
        conv.kind("quiz", phase="asking")
        conv.say("skip")
        conv.kind("quiz", phase="ended")
    assert item_id in [i["id"] for i in client.get("/api/reviews/due").json()["items"]]


def test_asking_for_a_quiz_by_voice_enters_quiz_mode(client: TestClient) -> None:
    seed()
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.say("quiz me")
        conv.kind("mode", mode="recall_quiz")
        assert conv.kind("quiz", phase="asking")["prompt"] == PROMPT


def test_nothing_due_says_so_and_a_topic_with_no_notes_is_handled(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.say("quiz me")
        assert conv.kind("quiz", phase="empty")["phase"] == "empty"
        conv.kind("assistant_done")
        assert "no" in conv.spoken().lower() or "nothing" in conv.spoken().lower()

        conv.say("quiz me on zebras")
        conv.kind("assistant_done")
        assert "zebras" in conv.spoken()


def test_cloze_questions_are_spoken_with_the_blank_named(client: TestClient) -> None:
    seed_note(
        "Cosine similarity",
        "Cosine similarity compares embedding direction.",
        [("Cosine _____ compares embedding direction.", "similarity", PromptKind.cloze)],
    )
    with client.websocket_connect("/ws/voice") as ws:
        conv = open_quiz(ws)
        conv.kind("quiz", phase="asking")
        conv.kind("assistant_done")
        assert "Fill in the blank. Cosine blank compares embedding direction." in conv.spoken()


def test_the_due_endpoint_hides_answers_and_grade_endpoint_schedules(client: TestClient) -> None:
    _, item_id = seed()
    due = client.get("/api/reviews/due?track=ai-eng").json()
    assert due["total_due"] == 1
    item = due["items"][0]
    assert item["prompt"] == PROMPT and "answer" not in item and item["retrievability"] is None

    graded = client.post(f"/api/reviews/{item_id}/grade", json={"grade": "good"}).json()
    assert graded["became_fragile"] is False
    assert datetime.fromisoformat(graded["next_due_at"]) > datetime.now(UTC)
    assert client.get("/api/reviews/due").json()["total_due"] == 0
    assert client.post(f"/api/reviews/{item_id}/grade", json={"grade": "meh"}).status_code == 422
    missing = "00000000-0000-0000-0000-0000000000aa"
    assert client.post(f"/api/reviews/{missing}/grade", json={"grade": "good"}).status_code == 404

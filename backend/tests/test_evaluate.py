"""Evaluate an explanation against the learner's own notes or PDF."""

import pytest
from fastapi.testclient import TestClient

from app.agent.router import Mode, Route, route_by_rules
from app.agent.schemas import AccuracyCheck, Contradiction
from app.services import accuracy as accuracy_svc
from app.services.reference import Reference
from tests.helpers import Conv, seed_note


@pytest.mark.parametrize(
    ("text", "topic"),
    [
        ("evaluate me on binary search", "binary search"),
        ("Aria, test my understanding of RAG", "RAG"),
        ("check my explanation against my notes on hash maps", "hash maps"),
        ("evaluate my explanation", None),
        ("evaluate me on my pdf", None),
    ],
)
def test_asking_to_be_evaluated(text: str, topic: str | None) -> None:
    assert route_by_rules(text, Mode.capture) == Route(
        Mode.teach_back, topic=topic, command="start_eval"
    )


def test_quiz_me_is_still_a_quiz() -> None:
    assert route_by_rules("quiz me", Mode.capture) == Route(Mode.recall_quiz, command="start")


# ---- the checker is held to what was actually said ----


def check(raw: AccuracyCheck, transcript: str) -> accuracy_svc.Accuracy:
    return accuracy_svc.validate(raw, transcript, "your notes")


def test_a_contradiction_counts_only_if_the_quote_was_really_said() -> None:
    raw = AccuracyCheck(
        covered=["halving the range"],
        missed=["it needs sorted input"],
        contradicted=[
            Contradiction(said="it works on unsorted data", reference="the input must be sorted"),
            Contradiction(said="something you never said", reference="made up"),
        ],
    )
    result = check(raw, "Binary search halves the range. It works on unsorted data too, I think.")
    assert [c.said for c in result.contradicted] == ["it works on unsorted data"]


def test_the_spoken_summary_names_what_matched_what_conflicted_and_what_was_missed() -> None:
    result = accuracy_svc.Accuracy(
        against="your notes (Binary search)",
        covered=["halving the range", "the loop"],
        missed=["sorted input"],
        contradicted=[Contradiction(said="it is O of n", reference="it is O of log n")],
    )
    spoken = result.spoken()
    assert spoken.startswith("Checking against your notes (Binary search).")
    assert "You covered halving the range and the loop." in spoken
    assert "you said it is O of n, but your notes say it is O of log n" in spoken
    assert "You didn't mention sorted input." in spoken


def test_a_reference_describes_where_it_came_from() -> None:
    assert Reference().about() == "your notes" and Reference().empty
    assert Reference("x", ["Guide"], True).about() == "your notes and Guide"
    assert Reference("x", ["Binary search"], False).about() == "your notes (Binary search)"


# ---- end to end ----


def make_notes(client: TestClient) -> None:
    book = client.post("/api/notebooks", json={"track": "dsa", "name": "Binary search"}).json()
    for title, body in (
        ("Binary search halves the range", "Each step halves the sorted range."),
        ("Binary search needs sorted input", "The array must already be sorted."),
    ):
        note, _ = seed_note(title, body, track_slug="dsa")
        client.patch(f"/api/notes/{note}", json={"notebook_id": book["id"]})


EXPLANATION = (
    "Binary search looks at the middle of the list and halves the range every step until it finds "
    "the value, which makes lookups very quick even when the list is huge."
)


def test_evaluating_an_explanation_against_the_notes_names_covered_and_missed_points(
    client: TestClient,
) -> None:
    make_notes(client)
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("dsa")
        conv.say("evaluate me on binary search")
        listening = conv.kind("teachback", phase="listening")
        assert "Binary search" in listening["checking"]
        conv.kind("assistant_done")
        assert "check it against your notes" in conv.spoken()

        conv.say(EXPLANATION)
        conv.say("I'm done")
        scored = conv.kind("teachback", phase="scored")
        accuracy = scored["accuracy"]
        assert accuracy["covered"] == ["Binary search halves the range"]
        assert accuracy["missed"] == ["Binary search needs sorted input"]
        conv.kind("assistant_done")
        spoken = conv.spoken()
        assert "Checking against your notes" in spoken
        assert "You didn't mention Binary search needs sorted input" in spoken


def test_without_notes_to_check_against_it_says_so_and_still_scores_the_explanation(
    client: TestClient,
) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("dsa")
        conv.say("evaluate me on zebras")
        listening = conv.kind("teachback", phase="listening")
        assert listening["checking"] == ""
        conv.kind("assistant_done")
        assert "I don't have notes on zebras to check against" in conv.spoken()
        conv.say(EXPLANATION)
        conv.say("I'm done")
        scored = conv.kind("teachback", phase="scored")
        assert scored["accuracy"] is None and scored["clarity"] is not None


def test_a_plain_teach_back_is_not_checked_against_notes(client: TestClient) -> None:
    make_notes(client)
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("dsa")
        conv.send(type="teachback_start", topic="binary search")
        assert conv.kind("teachback", phase="listening")["checking"] == ""
        conv.say(EXPLANATION)
        conv.say("I'm done")
        assert conv.kind("teachback", phase="scored")["accuracy"] is None


def test_the_button_can_ask_for_an_evaluation(client: TestClient) -> None:
    make_notes(client)
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("dsa")
        conv.send(type="teachback_start", topic="binary search", evaluate=True)
        assert "Binary search" in conv.kind("teachback", phase="listening")["checking"]

"""Notebooks by voice, worked discussions, recitation with questions, overview diagrams."""

from typing import Any

from fastapi.testclient import TestClient

from app.db.models import PromptKind
from tests.helpers import Conv, seed_note


def notebooks(client: TestClient, track: str | None = None) -> list[dict[str, Any]]:
    url = "/api/notebooks" + (f"?track={track}" if track else "")
    out: list[dict[str, Any]] = client.get(url).json()
    return out


def file_note(client: TestClient, note_id: Any, notebook_id: str) -> None:
    assert (
        client.patch(f"/api/notes/{note_id}", json={"notebook_id": notebook_id}).status_code == 200
    )


# ---- "create a new notes file for binary search under dsa" ----


def test_creating_a_notes_file_by_voice_switches_track_and_files_notes_into_it(
    client: TestClient,
) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("ai-eng")
        conv.say("create a new notes file for binary search under dsa")
        conv.kind("session", track="dsa")  # the connection moved to the dsa track
        nb = conv.kind("notebook", name="Binary search")
        assert nb["track"] == "dsa" and nb["created"] is True and nb["kind"] == "notes"
        conv.kind("assistant_done")
        assert "Binary search" in conv.spoken() and "goes into it" in conv.spoken()

        conv.say("Binary search halves the sorted range on every single step.")
        conv.kind("notes")
    [book] = notebooks(client, "dsa")
    assert book["name"] == "Binary search" and book["note_count"] == 1
    [note] = client.get("/api/notes?track=dsa").json()
    assert note["notebook_id"] == book["id"]
    assert client.get("/api/notes?track=ai-eng").json() == []


def test_several_files_at_once_start_with_the_first(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("dsa")
        conv.say("create notes files for binary and hashmap under dsa")
        conv.kind("notebook", name="Binary")
        conv.kind("assistant_done")
        assert "2 notes files" in conv.spoken() and "open Hashmap notes" in conv.spoken()
    assert {b["name"] for b in notebooks(client, "dsa")} == {"Binary", "Hashmap"}


def test_opening_an_existing_file_and_closing_it(client: TestClient) -> None:
    book = client.post("/api/notebooks", json={"track": "dsa", "name": "Hash map"}).json()
    note, _ = seed_note("Hash maps are fast", "O(1) on average.", track_slug="dsa")
    file_note(client, note, book["id"])
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("dsa")
        conv.say("open my hash map notes")
        opened = conv.kind("notebook", name="Hash map")
        assert opened["note_count"] == 1 and opened["created"] is False
        conv.kind("assistant_done")
        assert "1 note" in conv.spoken()

        conv.say("close the notebook")
        assert conv.kind("notebook", notebook_id=None)["name"] == ""


def test_opening_a_file_that_does_not_exist_says_so(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("dsa")
        conv.say("open my graphs notes")
        conv.kind("assistant_done")
        assert "couldn't find notes called graphs" in conv.spoken().lower()
    assert notebooks(client) == []


def test_the_ui_can_pick_a_notebook_even_in_another_track(client: TestClient) -> None:
    book = client.post("/api/notebooks", json={"track": "dsa", "name": "Trees"}).json()
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("ai-eng")
        conv.send(type="notebook_open", notebook_id=book["id"])
        conv.kind("session", track="dsa")
        conv.kind("notebook", name="Trees")


# ---- "let's discuss designing a URL shortener" ----


def test_a_worked_discussion_suggests_evaluates_and_wraps_up(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("ai-eng")
        conv.say("create a new notes for system design where we discuss and solve the question")
        conv.kind("session", track="solutions")
        conv.kind("mode", mode="discuss")
        conv.kind("assistant_done")
        book = next(e for e in conv.of("notebook") if e["kind"] == "discussion" and e["name"])
        assert book["name"] == "System design"
        assert "What problem" in conv.spoken()  # no problem named yet, so it asks which one

        conv.say("Let's design a URL shortener with a key value store.")
        conv.kind("assistant_done")
        assert "My suggestion" in conv.spoken()  # it evaluates, suggests and asks
        conv.kind("notes")  # and the learner's words became notes
        renamed = [
            e for e in conv.of("notebook") if e["name"] == "URL shortener with a key value store"
        ]
        assert renamed  # the notebook took the problem's name

        conv.say("wrap up")
        conv.kind("mode", mode="capture")
        evaluation = (
            next(
                i
                for e in conv.of("notes")
                for i in e["items"]
                if i["title"].startswith("Evaluation:")
            )
            if conv.of("notes")
            else None
        )
        diagram = conv.kind("diagram")
        assert diagram["items"][0]["kind"] in ("mermaid", "steps")
        conv.kind("assistant_done")
        assert "saved the evaluation" in conv.spoken()
        assert evaluation is None or evaluation["origin"] == "assistant"

    notes = client.get("/api/notes?track=solutions").json()
    saved = [n for n in notes if n["title"].startswith("Evaluation:")]
    assert len(saved) == 1 and saved[0]["origin"] == "assistant" and saved[0]["confirmed"] is False
    assert all(n["notebook_id"] == book["notebook_id"] for n in notes)
    assert [b["name"] for b in notebooks(client, "solutions")] == [
        "URL shortener with a key value store"
    ]


def test_leaving_a_discussion_early_keeps_the_notes(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("solutions")
        conv.say("let's discuss designing a rate limiter")
        conv.kind("mode", mode="discuss")
        conv.kind("assistant_done")
        conv.say("exit the discussion")
        conv.kind("mode", mode="capture")
        conv.kind("assistant_done")
        assert "leaving the discussion" in conv.spoken()
    assert len(notebooks(client, "solutions")) == 1


# ---- "start reciting the notes": explain each note and ask in between ----


def recite_notebook(client: TestClient) -> str:
    book = client.post("/api/notebooks", json={"track": "dsa", "name": "Binary search"}).json()
    for title, body, q, a in (
        (
            "Binary search halves the range",
            "Each step halves the sorted range.",
            "What does each step halve?",
            "the range",
        ),
        (
            "It needs sorted input",
            "The array must already be sorted.",
            "What must be true of the input?",
            "sorted",
        ),
    ):
        note, _ = seed_note(title, body, [(q, a, PromptKind.question)], track_slug="dsa")
        file_note(client, note, book["id"])
    return str(book["id"])


def test_reciting_explains_each_note_and_checks_recall_between_notes(client: TestClient) -> None:
    recite_notebook(client)
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("dsa")
        conv.say("start reciting my binary search notes")
        first = conv.kind("read_back", index=0)
        assert first["total"] == 2 and first["title"] == "Binary search halves the range"
        asked = conv.kind("quiz", phase="asking")
        assert asked["prompt"] == "What does each step halve?"
        conv.kind("assistant_done")
        spoken = conv.spoken()
        assert "In plain words" in spoken and "Let me check that" in spoken  # it explained it

        conv.say("it halves the range")
        assert conv.kind("quiz", phase="graded")["grade"] in ("Good", "Easy")
        second = conv.kind("read_back", index=1)  # then it moved on by itself
        assert second["title"] == "It needs sorted input"
        assert conv.kind("quiz", phase="asking")["prompt"] == "What must be true of the input?"
        conv.kind("assistant_done")

        conv.say("it has to be sorted")
        conv.kind("quiz", phase="graded")
        conv.kind("mode", mode="capture")
        conv.kind("assistant_done")
        assert "all of Binary search" in conv.spoken()


def test_stopping_during_a_recitation_ends_all_of_it(client: TestClient) -> None:
    recite_notebook(client)
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("dsa")
        conv.say("recite my binary search notes")
        conv.kind("quiz", phase="asking")
        conv.kind("assistant_done")
        conv.say("stop")
        conv.kind("mode", mode="capture")
        conv.kind("assistant_done")
        assert "stopping the recitation" in conv.spoken()
        assert not conv.of("session_end")


def test_the_recite_button_uses_the_notebook(client: TestClient) -> None:
    book_id = recite_notebook(client)
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("dsa")
        conv.send(type="recite_start", notebook_id=book_id)
        assert conv.kind("read_back", index=0)["total"] == 2


def test_reciting_something_that_has_no_notes(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("dsa")
        conv.say("recite my graph notes")
        conv.kind("assistant_done")
        assert "don't have any notes" in conv.spoken()


def test_plain_read_back_still_reads_without_interrupting_with_questions(
    client: TestClient,
) -> None:
    recite_notebook(client)
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("dsa")
        conv.say("read me my notes on binary search")
        conv.kind("read_back", index=0)
        conv.kind("assistant_done")
        assert "Say next to continue" in conv.spoken()
        assert not conv.of("quiz")


# ---- "draw the architecture" while reciting a design ----


def test_drawing_the_overview_of_the_open_notebook(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("solutions")
        conv.say("create a notes file for chat design")
        conv.kind("notebook", name="Chat design")
        conv.kind("assistant_done")
        conv.say("Clients connect to a gateway over websockets for live delivery.")
        conv.kind("notes")
        conv.say("Messages are stored in a partitioned wide column database by chat id.")
        conv.kind("notes")
        conv.say("draw the architecture")
        diagram = conv.kind("diagram")
        assert diagram["items"][0]["kind"] in ("mermaid", "steps")
        conv.kind("assistant_done")
        assert "overview of Chat design" in conv.spoken()
    overview = [
        n
        for n in client.get("/api/notes?track=solutions").json()
        if n["title"] == "Overview: Chat design"
    ]
    assert len(overview) == 1 and overview[0]["origin"] == "assistant"


def test_drawing_with_no_notebook_open_asks_for_one(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("solutions")
        conv.say("draw the diagram")
        conv.kind("assistant_done")
        assert "Open or create a notes file first" in conv.spoken()

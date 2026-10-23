"""Aria: her name, knowing what she can do, and noticing the library change."""

import pytest
from fastapi.testclient import TestClient

from app.agent.router import Mode, Route, route_by_rules
from app.services import library as library_svc
from tests.helpers import Conv, seed_note


@pytest.mark.parametrize(
    "text",
    [
        "who are you",
        "what's your name",
        "what can you do",
        "What are you able to do?",
        "tell me about yourself",
        "what can I say",
        "help",
        "what's in my notes",
        "what notebooks do I have",
        "okay, what do you know about my notes",
    ],
)
def test_questions_about_aria_and_the_library_are_answered_not_explained(text: str) -> None:
    assert route_by_rules(text, Mode.capture) == Route(Mode.chitchat, command="about")


def test_other_what_are_questions_are_still_explanations() -> None:
    assert route_by_rules("what are embeddings", Mode.capture) == Route(
        Mode.explain, topic="embeddings"
    )


def test_her_name_in_front_of_a_command_is_ignored() -> None:
    assert route_by_rules("Aria, stop the session", Mode.capture) == Route(
        Mode.chitchat, command="end_session"
    )
    assert route_by_rules("Aria, quiz me", Mode.capture) == route_by_rules("quiz me", Mode.capture)
    assert route_by_rules("Aria", Mode.capture) == Route(Mode.chitchat, command="about")


def test_she_introduces_herself_and_names_what_is_in_the_library(client: TestClient) -> None:
    book = client.post("/api/notebooks", json={"track": "dsa", "name": "Binary search"}).json()
    note, _ = seed_note("Binary search halves the range", "Each step.", track_slug="dsa")
    client.patch(f"/api/notes/{note}", json={"notebook_id": book["id"]})
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("dsa")
        conv.say("what can you do?")
        conv.kind("assistant_done")
        spoken = conv.spoken()
        assert "I'm Aria" in spoken
        assert "Binary search" in spoken  # she can see the notebook


def test_the_persona_and_the_live_library_reach_every_conversational_prompt(
    client: TestClient,
) -> None:
    seen: list[str] = []
    deps = client.app.state.deps  # type: ignore[attr-defined]
    inner = deps.llm

    class Spy:
        async def complete_structured(self, *a: object, **k: object) -> object:
            return await inner.complete_structured(*a, **k)

        def stream_text(self, *a: object, **k: object) -> object:
            seen.append(str(k["system"]))
            return inner.stream_text(*a, **k)

    deps.llm = Spy()
    client.post("/api/notebooks", json={"track": "dsa", "name": "Graphs"})
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("dsa")
        conv.say("Binary search halves the sorted range on every single step.")  # capture ack
        conv.kind("assistant_done")
        conv.say("explain heaps")
        conv.kind("assistant_done")
        conv.say("what can you do?")  # about her
        conv.kind("assistant_done")
    assert len(seen) >= 3
    for system in seen:
        assert "You are Aria" in system and "WHAT YOU CAN DO" in system
        assert "- Graphs (notes, 0 notes)" in system  # the library as it is right now


def test_a_new_notebook_appearing_elsewhere_is_announced_once(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("ai-eng")
        # Made by something else while she is listening (another device, an upload, n8n).
        client.post("/api/notebooks", json={"track": "dsa", "name": "Tries"})
        conv.say("Retrieval finds relevant chunks before generation happens.")
        conv.kind("assistant_done")
        assert "I noticed a new notes file, Tries" in conv.spoken()
        assert "recite" in conv.spoken()

        before = conv.spoken()
        conv.say("Chunk overlap keeps context across the boundaries well.")
        conv.kind("assistant_done")
        assert conv.spoken().count("I noticed a new notes file") == 1 and before


def test_notebooks_made_in_this_conversation_are_not_announced_back_to_her(
    client: TestClient,
) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("dsa")
        conv.say("create notes files for binary and hashmap under dsa")
        conv.kind("assistant_done")
        conv.say("Binary search halves the sorted range on every single step.")
        conv.kind("assistant_done")
        assert "I noticed" not in conv.spoken()


def test_heads_up_wording() -> None:
    one = library_svc.NewNotebook(
        id=__import__("uuid").uuid4(),
        name="Tries",
        track_name="Data Structures",
        kind="notes",
        notes=3,
    )
    assert library_svc.heads_up([one]) == (
        "By the way, I noticed a new notes file, Tries, in Data Structures with 3 notes. "
        "Say recite if you'd like to go through it."
    )
    src = library_svc.NewNotebook(one.id, "Big Guide", "AI Engineering", "source", 7)
    assert "from a source with 7 notes" in library_svc.heads_up([src])
    assert library_svc.heads_up([]) == ""
    assert "2 new notes files" in library_svc.heads_up([one, src])

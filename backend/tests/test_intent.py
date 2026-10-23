"""Aria understands requests that are not worded like any fixed phrase."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.agent.router import (
    Mode,
    Route,
    route_by_rules,
    route_from_intent,
    route_turn,
    wants_intent,
)
from app.agent.schemas import Intent
from tests.helpers import Conv, ScriptedLLM

# ---- which sentences are worth a model call (thinking aloud must stay instant) ----


@pytest.mark.parametrize(
    "text",
    [
        "Could you set me up a notebook for binary search under dsa",
        "I'd love to have a place for graphs",
        "I want you to go over my heap notes",
        "can you put hash maps somewhere under dsa?",
        "is there anything on tries in my notes",
        "Aria, I need a file for linked lists",
        "what did we say about sharding",
    ],
)
def test_requests_are_sent_to_the_model(text: str) -> None:
    assert wants_intent(text)


@pytest.mark.parametrize(
    "text",
    [
        "Hash maps make lookups fast on average.",
        "Binary search halves the range each step so it is logarithmic.",
        "The notebook idea is that you keep related notes together.",
        "so the load balancer sends requests to the least busy server",
        "",
    ],
)
def test_thinking_aloud_never_waits_for_the_model(text: str) -> None:
    assert not wants_intent(text)


def test_a_long_monologue_is_never_treated_as_a_command() -> None:
    long_text = "can you imagine " + "a very long explanation about caching " * 10
    assert not wants_intent(long_text)


def test_a_note_is_kept_without_calling_the_model() -> None:
    llm = ScriptedLLM()  # raises if it is called
    route = asyncio.run(route_turn(llm, "Hash maps make lookups fast.", Mode.capture))
    assert route == Route(Mode.capture) and llm.users == []


# ---- meaning, not phrases ----


def routed(intent: Intent, text: str = "could you set me up something") -> Route:
    llm = ScriptedLLM(intent)
    return asyncio.run(route_turn(llm, text, Mode.capture))


def test_the_rules_do_not_know_this_sentence_but_the_model_does() -> None:
    text = "Could you set me up a notebook for binary search under dsa"
    assert route_by_rules(text, Mode.capture) is None  # no fixed phrase matches
    route = routed(Intent(intent="create_notebook", names=["binary search"], track="dsa"), text)
    assert route == Route(
        Mode.capture, command="notebook_new", names=("binary search",), track="dsa"
    )


def test_each_understood_intent_becomes_the_right_route() -> None:
    cases = {
        "open_notebook": (Intent(intent="open_notebook", names=["graphs"]), "notebook_open"),
        "close_notebook": (Intent(intent="close_notebook"), "notebook_close"),
        "write_notes": (
            Intent(intent="write_notes", names=["heaps"], track="dsa"),
            "notebook_draft",
        ),
        "discuss": (Intent(intent="discuss", topic="a rate limiter"), "start"),
        "recite": (Intent(intent="recite", topic="heaps"), "recite"),
        "evaluate": (Intent(intent="evaluate", topic="heaps"), "start_eval"),
        "draw": (Intent(intent="draw"), "draw"),
        "end_session": (Intent(intent="end_session"), "end_session"),
        "about": (Intent(intent="about"), "about"),
    }
    for name, (intent, command) in cases.items():
        route = route_from_intent(intent)
        assert route is not None and route.command == command, name
    assert route_from_intent(Intent(intent="discuss", topic="x")).track == "solutions"  # type: ignore[union-attr]
    assert route_from_intent(Intent(intent="create_notebook", names=["a"], write_notes=True)).draft  # type: ignore[union-attr]


def test_not_a_request_means_keep_listening_or_answer_a_question() -> None:
    assert route_from_intent(Intent(intent="none")) is None
    llm = ScriptedLLM(Intent(intent="none"))
    assert asyncio.run(route_turn(llm, "can you believe how fast that is", Mode.capture)) == Route(
        Mode.capture
    )
    llm = ScriptedLLM(Intent(intent="none"))
    assert asyncio.run(route_turn(llm, "is that right?", Mode.capture)) == Route(Mode.chitchat)


def test_a_request_with_no_name_asks_for_one_instead_of_guessing() -> None:
    route = route_from_intent(Intent(intent="create_notebook"))
    assert (
        route is not None
        and route.command == "clarify"
        and "call the notes file" in (route.topic or "")
    )


def test_the_model_can_ask_what_was_meant() -> None:
    route = route_from_intent(
        Intent(intent="unclear", clarify="Did you want a notes file called heaps?")
    )
    assert route == Route(
        Mode.chitchat, command="clarify", topic="Did you want a notes file called heaps?"
    )


def test_the_model_is_given_the_library_to_resolve_names() -> None:
    llm = ScriptedLLM(Intent(intent="open_notebook", names=["Binary search"]))

    async def context() -> str:
        return "Notebooks in this track:\n- Binary search (notes, 2 notes)"

    asyncio.run(
        route_turn(llm, "can you go back to my binary one", Mode.capture, context_fn=context)
    )
    assert "- Binary search (notes, 2 notes)" in llm.users[0]
    assert "LEARNER SAID:\ncan you go back to my binary one" in llm.users[0]


def test_sticky_modes_are_not_slowed_down_by_the_model() -> None:
    llm = ScriptedLLM()
    route = asyncio.run(route_turn(llm, "next", Mode.read_back))
    assert route == Route(Mode.read_back, command="next") and llm.users == []


# ---- end to end, in loosely worded sentences ----


def test_loosely_worded_requests_work_by_voice(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("ai-eng")
        conv.say("Could you set up a notebook for my binary search stuff in dsa please")
        conv.kind("session", track="dsa")
        conv.kind("notebook", name="My binary search stuff")
        conv.kind("assistant_done")


def test_an_unclear_request_gets_a_question_not_a_note(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("dsa")
        conv.say("maybe you could do something with my notes")
        conv.kind("assistant_done")
        assert "Did you want me to make a notes file?" in conv.spoken()
    assert client.get("/api/notes?track=dsa").json() == []

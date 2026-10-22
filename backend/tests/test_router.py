import asyncio

import pytest

from app.agent.router import Mode, Route, RouteDecision, route_by_rules, route_turn
from tests.helpers import ScriptedLLM


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Quiz me", Route(Mode.recall_quiz, command="start")),
        ("test me on this", Route(Mode.recall_quiz, command="start")),
        ("what's due today", Route(Mode.recall_quiz, command="start")),
        ("Quiz me on chunking", Route(Mode.recall_quiz, topic="chunking", command="start")),
        ("Read me my notes on RAG", Route(Mode.read_back, topic="RAG", command="start")),
        (
            "read back my notes about embeddings.",
            Route(Mode.read_back, topic="embeddings", command="start"),
        ),
        ("read me my notes", Route(Mode.read_back, command="start")),
        (
            "Explain retrieval augmented generation",
            Route(Mode.explain, topic="retrieval augmented generation"),
        ),
        ("how does reranking work?", Route(Mode.explain, topic="reranking")),
        ("What is a vector database", Route(Mode.explain, topic="a vector database")),
    ],
)
def test_obvious_commands_route_without_an_llm(text: str, expected: Route) -> None:
    assert route_by_rules(text, Mode.capture) == expected


@pytest.mark.parametrize(
    "text",
    [
        "RAG retrieves relevant documents before generation.",
        "I think the retriever is the hard part",
        "um so basically embeddings map text to vectors",
    ],
)
def test_explaining_is_capture_by_default(text: str) -> None:
    assert route_by_rules(text, Mode.capture) is None


@pytest.mark.parametrize(
    ("text", "command"),
    [
        ("I forgot", "forgot"),
        ("I don't know", "forgot"),
        ("give me a hint", "hint"),
        ("skip this one", "skip"),
        ("stop the quiz", "end"),
        ("It uses cosine similarity to rank the chunks by closeness", "answer"),
    ],
)
def test_in_a_quiz_speech_is_an_answer_unless_it_is_a_command(text: str, command: str) -> None:
    assert route_by_rules(text, Mode.recall_quiz) == Route(Mode.recall_quiz, command=command)


def test_a_long_answer_containing_a_command_word_is_still_an_answer() -> None:
    text = "You would stop the process once the retrieved context fits in the window"
    assert route_by_rules(text, Mode.recall_quiz) == Route(Mode.recall_quiz, command="answer")


@pytest.mark.parametrize(
    ("text", "command"),
    [
        ("next", "next"),
        ("slower", "slower"),
        ("repeat that", "repeat"),
        ("skip", "skip"),
        ("stop", "stop"),
    ],
)
def test_read_back_pace_commands(text: str, command: str) -> None:
    assert route_by_rules(text, Mode.read_back) == Route(Mode.read_back, command=command)


def test_an_unmatched_statement_never_calls_the_llm() -> None:
    llm = ScriptedLLM()  # would raise if called
    assert asyncio.run(route_turn(llm, "RAG helps a lot.", Mode.capture)) == Route(Mode.capture)
    assert llm.users == []


def test_an_ambiguous_question_falls_back_to_the_fast_model() -> None:
    llm = ScriptedLLM(RouteDecision(mode=Mode.explain, topic="attention"))
    route = asyncio.run(
        route_turn(llm, "so is attention the thing that weights tokens?", Mode.capture)
    )
    assert route == Route(Mode.explain, topic="attention")
    assert len(llm.users) == 1


def test_the_llm_router_can_start_teach_back() -> None:
    llm = ScriptedLLM(RouteDecision(mode=Mode.teach_back))
    route = asyncio.run(route_turn(llm, "is this right?", Mode.capture))
    assert route == Route(Mode.teach_back, command="start")

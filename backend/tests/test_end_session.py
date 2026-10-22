import pytest
from fastapi.testclient import TestClient

from app.agent.router import Mode, Route, route_by_rules
from app.db.models import PromptKind
from tests.helpers import Conv, seed_note

END = Route(Mode.chitchat, command="end_session")


@pytest.mark.parametrize(
    "text",
    [
        "stop",
        "Stop the session.",
        "okay, end session",
        "End the conversation",
        "stop listening",
        "goodbye",
        "bye",
        "that's all for today",
        "we're done",
        "I'm done for now",
        "see you later",
    ],
)
def test_ending_the_session_by_voice(text: str) -> None:
    assert route_by_rules(text, Mode.capture) == END


@pytest.mark.parametrize(
    "text",
    [
        "Stop words are removed during preprocessing.",
        "The end of the sequence token tells the model to stop generating.",
        "I'm done with the first part of the pipeline, now the reranker.",
        "bye bye is not a thing I need to explain right now because retrieval matters more",
    ],
)
def test_sentences_that_merely_contain_those_words_are_still_notes(text: str) -> None:
    assert route_by_rules(text, Mode.capture) != END


def test_stop_inside_a_quiz_ends_the_quiz_not_the_session() -> None:
    assert route_by_rules("stop", Mode.recall_quiz) == Route(Mode.recall_quiz, command="end")
    assert route_by_rules("stop", Mode.teach_back) == Route(Mode.teach_back, command="cancel")


def test_the_server_tells_the_client_to_close_the_mic_and_says_goodbye(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.say("stop the session")
        conv.kind("session_end")
        conv.kind("assistant_done")
        assert "ending the session" in conv.spoken().lower()
    assert client.get("/api/notes?track=ai-eng").json() == []  # not filed as a note


def test_a_quiz_stop_does_not_close_the_session(client: TestClient) -> None:
    seed_note(
        "Chunks",
        "RAG splits text into chunks.",
        [("What does RAG split?", "text", PromptKind.question)],
    )
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.send(type="quiz")
        conv.kind("quiz", phase="asking")
        conv.say("stop")
        conv.kind("quiz", phase="ended")
        assert not conv.of("session_end")

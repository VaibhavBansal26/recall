import pytest

from app.agent import commands as c


@pytest.mark.parametrize(
    ("text", "names", "track"),
    [
        ("create a new notes file for binary search under dsa", ("binary search",), "dsa"),
        ("Create new notes for hash map in the dsa folder", ("hash map",), "dsa"),
        ("create a notes file for binary and hashmap under dsa", ("binary", "hashmap"), "dsa"),
        (
            "create notes for binary search, hash map and two pointers in DSA",
            ("binary search", "hash map", "two pointers"),
            "dsa",
        ),
        (
            "make a new notebook on attention mechanisms for ai concepts",
            ("attention mechanisms",),
            "ai-eng",
        ),
        ("create a new note file for RAG", ("RAG",), None),
        ("okay, create 1 notes file for graphs under dsa.", ("graphs",), "dsa"),
        ("under dsa create a new notes file for tries", ("tries",), "dsa"),
        ("start a new notebook called vector databases", ("vector databases",), None),
    ],
)
def test_creating_notebooks_by_voice(text: str, names: tuple[str, ...], track: str | None) -> None:
    cmd = c.parse_notebook(text)
    assert cmd is not None and cmd.kind == "new"
    assert cmd.names == names and cmd.track == track


@pytest.mark.parametrize(
    ("text", "name", "track"),
    [
        ("open my binary search notes", "binary search", None),
        ("switch to the hash map notebook", "hash map", None),
        ("go back to graphs notes in dsa", "graphs", "dsa"),
        ("add this to the RAG notes", "RAG", None),
    ],
)
def test_opening_a_notebook(text: str, name: str, track: str | None) -> None:
    cmd = c.parse_notebook(text)
    assert cmd == c.NotebookCommand("open", (name,), track)


def test_closing_and_non_commands() -> None:
    assert c.parse_notebook("close the notebook") == c.NotebookCommand("close")
    assert c.parse_notebook("done with this file") == c.NotebookCommand("close")
    for text in (
        "binary search halves the range each step",
        "I want to create a cache for the notes service",
        "open source models are getting better",
        "read me my notes on binary search",
    ):
        assert c.parse_notebook(text) is None, text


@pytest.mark.parametrize(
    "text",
    [
        "create a new notes for system design where we discuss and solve the question",
        "let's discuss designing a URL shortener",
        "let's solve the two sum problem",
        "I want to start a system design discussion on a rate limiter",
        "let's design a chat application",
    ],
)
def test_starting_a_discussion(text: str) -> None:
    cmd = c.parse_discuss(text)
    assert cmd is not None and cmd.kind == "start" and cmd.track == "solutions"


def test_discussion_topics_are_cleaned() -> None:
    assert (
        c.parse_discuss("let's discuss designing a URL shortener").topic
        == "designing a URL shortener"
    )  # type: ignore[union-attr]
    assert (
        c.parse_discuss("I want to start a system design discussion on a rate limiter").topic
        == "rate limiter"
    )  # type: ignore[union-attr]


def test_not_a_discussion() -> None:
    for text in (
        "let's go through my notes",
        "binary search is a great pattern",
        "do my notes on rag",
    ):
        assert c.parse_discuss(text) is None, text


def test_wrapping_up_and_leaving_a_discussion() -> None:
    for text in (
        "wrap up",
        "okay, summarize",
        "evaluate my design",
        "how did I do",
        "that's my final design",
    ):
        assert c.discuss_followup(text) == "wrap", text
    for text in ("stop", "exit the discussion", "never mind"):
        assert c.discuss_followup(text) == "end", text
    assert c.discuss_followup("I would shard the database by user id") is None


@pytest.mark.parametrize(
    ("text", "topic", "track"),
    [
        ("start reciting my binary search notes", "binary search", None),
        ("recite the notes", None, None),
        ("recite my hash map notes in dsa", "hash map", "dsa"),
        ("go through my notes on rag", "rag", None),
        ("let's revise binary search", "binary search", None),
        ("go over the notes", None, None),
    ],
)
def test_reciting(text: str, topic: str | None, track: str | None) -> None:
    cmd = c.parse_recite(text)
    assert cmd == c.ReciteCommand(topic, track)


def test_recite_ignores_other_sentences() -> None:
    for text in (
        "go through the problem statement slowly",
        "I can recite the alphabet",
        "teach me something",
    ):
        assert c.parse_recite(text) is None or text.startswith("I can"), text


def test_draw_the_diagram() -> None:
    for text in (
        "draw the architecture",
        "show me the diagram",
        "generate the overall system diagram",
        "can you draw the diagram of it",
    ):
        assert c.is_draw(text), text
    assert not c.is_draw("the diagram shows two services")


def test_a_generic_system_design_request_leaves_the_problem_to_be_chosen() -> None:
    cmd = c.parse_discuss(
        "create a new notes for system design where we discuss and solve the question"
    )
    assert cmd is not None and cmd.topic == "system design" and c.is_generic_topic(cmd.topic or "")
    named = c.parse_discuss("let's discuss designing a URL shortener")
    assert named is not None and not c.is_generic_topic(named.topic or "")


def test_the_first_answer_names_a_generic_discussion() -> None:
    assert (
        c.problem_from("Let's design a URL shortener with a key value store.")
        == "URL shortener with a key value store"
    )
    assert c.problem_from("I want to discuss a rate limiter") == "rate limiter"
    assert c.problem_from("...") == "System design"

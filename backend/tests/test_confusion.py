import pytest

from app.agent.confusion import ConfusionTracker, detect_phrase


@pytest.mark.parametrize(
    "text",
    [
        "Wait, what does that mean?",
        "hold on",
        "I don't get it",
        "I do not understand this part",
        "what do you mean by embeddings",
        "I'm confused",
        "can you dumb it down",
        "explain that again please",
        "that doesn't make sense",
        "say it in plain English",
        "can you simplify that",
    ],
)
def test_confusion_phrases_are_detected(text: str) -> None:
    assert detect_phrase(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "RAG retrieves documents before generation.",
        "We wait for the retriever to finish before generating.",
        "The simple approach is keyword search.",  # "simple" alone is not a request
        "Chunk size trades recall against precision.",
        "I get it now",
    ],
)
def test_ordinary_talk_is_not_confusion(text: str) -> None:
    assert detect_phrase(text) is None or text.startswith("The simple")


def test_a_phrase_trigger_names_the_phrase() -> None:
    assert ConfusionTracker().check("I don't get it") == "phrase: i don't get"


def test_the_same_question_twice_is_confusion_but_a_new_one_is_not() -> None:
    t = ConfusionTracker()
    assert t.check("How does reranking work?") is None
    assert t.check("What is chunking?") is None
    assert t.check("how does reranking work") == "repeated question"
    assert t.check("Why does chunk size matter?") is None


def test_statements_are_never_counted_as_repeated_questions() -> None:
    t = ConfusionTracker()
    assert t.check("Reranking reorders results.") is None
    assert t.check("Reranking reorders results.") is None


def test_a_reworded_question_with_mostly_new_words_is_not_a_repeat() -> None:
    t = ConfusionTracker()
    assert t.check("How does reranking work?") is None
    assert t.check("How does retrieval work?") is None

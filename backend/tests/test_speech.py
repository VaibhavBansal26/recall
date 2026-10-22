from app.voice.speech import SentenceChunker, clean_for_speech


def chunk(tokens: list[str]) -> list[str]:
    chunker = SentenceChunker()
    out: list[str] = []
    for t in tokens:
        out += chunker.feed(t)
    if (tail := chunker.flush()) is not None:
        out.append(tail)
    return out


def test_emits_each_sentence_as_soon_as_it_ends() -> None:
    chunker = SentenceChunker()
    assert chunker.feed("Got it, noted") == []
    assert chunker.feed(".") == []  # a boundary needs the whitespace after the period
    assert chunker.feed(" Keep") == ["Got it, noted."]
    assert chunker.feed(" going") == []
    assert chunker.flush() == "Keep going"


def test_token_granularity_does_not_change_the_result() -> None:
    text = "RAG fetches context first. Then the model answers! Why does that help? Fewer guesses."
    whole = chunk([text])
    assert whole == chunk(list(text))
    assert whole == [
        "RAG fetches context first.",
        "Then the model answers!",
        "Why does that help?",
        "Fewer guesses.",
    ]


def test_does_not_split_on_abbreviations_or_decimals() -> None:
    assert chunk(["Use e.g. a vector store. It scores 0.88 on cosine."]) == [
        "Use e.g. a vector store.",
        "It scores 0.88 on cosine.",
    ]


def test_flush_on_empty_buffer_is_none() -> None:
    assert SentenceChunker().flush() is None


def test_clean_for_speech_strips_markdown_and_urls() -> None:
    raw = (
        "## Title\n- **Bold** point with `code` and [a link](https://x.io/a)\n"
        "See https://example.com now"
    )
    assert clean_for_speech(raw) == "Title Bold point with code and a link See now"


def test_clean_for_speech_drops_code_blocks_and_expands_symbols() -> None:
    assert clean_for_speech("Before ```py\nx=1\n``` after") == "Before after"
    assert clean_for_speech("Recall & precision -> 90%") == "Recall and precision to 90 percent"

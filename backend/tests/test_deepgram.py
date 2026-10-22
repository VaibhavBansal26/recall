from typing import Any

from app.voice.stt_deepgram import TranscriptAssembler


def results(text: str, *, final: bool, speech_final: bool = False, **extra: Any) -> dict[str, Any]:
    return {
        "type": "Results",
        "is_final": final,
        "speech_final": speech_final,
        "channel": {"alternatives": [{"transcript": text, "confidence": 0.98}]},
        **extra,
    }


def test_interim_results_become_partials_without_losing_earlier_finals() -> None:
    a = TranscriptAssembler()
    assert [(e.text, e.final) for e in a.feed(results("rag", final=False))] == [("rag", False)]
    assert [(e.text, e.final) for e in a.feed(results("rag retrieves", final=True))] == [
        ("rag retrieves", False)
    ]
    assert [(e.text, e.final) for e in a.feed(results("context", final=False))] == [
        ("rag retrieves context", False)
    ]


def test_speech_final_joins_fragments_into_one_final_utterance() -> None:
    a = TranscriptAssembler()
    a.feed(results("RAG retrieves context", final=True))
    done = a.feed(results("before generating.", final=True, speech_final=True))
    assert [(e.text, e.final, e.confidence) for e in done] == [
        ("RAG retrieves context before generating.", True, 0.98)
    ]
    assert a.flush() == []


def test_pause_mid_thought_does_not_end_the_utterance() -> None:
    a = TranscriptAssembler()
    assert not any(e.final for e in a.feed(results("so the idea is", final=True)))
    assert not any(e.final for e in a.feed(results("", final=False)))


def test_utterance_end_and_finalize_flush_pending_text() -> None:
    a = TranscriptAssembler()
    a.feed(results("first part", final=True))
    assert [e.final for e in a.feed({"type": "UtteranceEnd"})] == [True]
    a.feed(results("pressed and released", final=True, from_finalize=True))
    assert a.flush() == []  # already flushed by from_finalize


def test_ignores_unrelated_messages() -> None:
    assert TranscriptAssembler().feed({"type": "Metadata"}) == []

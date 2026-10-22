from typing import Any

import pytest

from app.config import Settings
from app.voice.pipeline import PipelineVoiceProvider
from app.voice.stt_elevenlabs import events_from_message


def test_partials_stream_through() -> None:
    [e] = events_from_message({"message_type": "partial_transcript", "text": "rag retrieves"})
    assert (e.text, e.final) == ("rag retrieves", False)
    assert events_from_message({"message_type": "partial_transcript", "text": " "}) == []


def test_a_committed_segment_is_final_and_keeps_word_timings_without_spacing() -> None:
    msg: dict[str, Any] = {
        "message_type": "committed_transcript_with_timestamps",
        "text": "RAG works.",
        "words": [
            {"text": "RAG", "start": 0.1, "end": 0.4, "type": "word"},
            {"text": " ", "start": 0.4, "end": 0.5, "type": "spacing"},
            {"text": "works.", "start": 0.5, "end": 0.9, "type": "word"},
        ],
    }
    [e] = events_from_message(msg)
    assert e.final and e.text == "RAG works."
    assert e.words == [
        {"w": "RAG", "start": 0.1, "end": 0.4},
        {"w": "works.", "start": 0.5, "end": 0.9},
    ]


def test_the_plain_committed_message_is_ignored_so_a_segment_is_not_doubled() -> None:
    assert events_from_message({"message_type": "committed_transcript", "text": "hi"}) == []


def test_other_messages_and_empty_commits_are_ignored() -> None:
    assert events_from_message({"message_type": "session_started"}) == []
    msg = {"message_type": "committed_transcript_with_timestamps", "text": "", "words": []}
    assert events_from_message(msg) == []


def settings(**kw: Any) -> Settings:
    return Settings(elevenlabs_api_key="k", elevenlabs_voice_id="v", **kw)  # type: ignore[arg-type]


def test_elevenlabs_stt_needs_only_the_elevenlabs_key() -> None:
    assert PipelineVoiceProvider(settings()).audio_input


def test_deepgram_stt_still_needs_its_own_key() -> None:
    with pytest.raises(ValueError, match="DEEPGRAM_API_KEY"):
        PipelineVoiceProvider(settings(stt_provider="deepgram"))
    assert PipelineVoiceProvider(settings(stt_provider="deepgram", deepgram_api_key="d"))

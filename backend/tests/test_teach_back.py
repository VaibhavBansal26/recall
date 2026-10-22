from typing import Any

from fastapi.testclient import TestClient

from app.services import sessions as sessions_svc
from app.voice.stt_deepgram import TranscriptAssembler
from tests.helpers import Conv, run_db

GOOD = [
    "A database index is a sorted structure that points at table rows.",
    "It works by keeping the keys in order, so a search can jump straight to the right place.",
    "This matters because lookups stay fast even when the table is huge, which means queries finish quickly.",
]


def start(conv: Conv, text: str = "let me explain how a database index works") -> None:
    conv.start()
    conv.say(text)
    conv.kind("mode", mode="teach_back")


def test_starting_a_teach_back_asks_for_the_explanation_and_does_not_chat(
    client: TestClient,
) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        start(conv)
        listening = conv.kind("teachback", phase="listening")
        assert listening["topic"] == "how a database index works" and listening["words"] == 0
        conv.kind("assistant_done")
        assert "Explain how a database index works in your own words" in conv.spoken()
        assert "say I'm done" in conv.spoken()


def test_while_the_learner_explains_it_only_listens_and_never_files_notes(
    client: TestClient,
) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        start(conv)
        conv.kind("teachback", phase="listening")  # the opening one, before anything was said
        conv.kind("assistant_done")
        counts = []
        for part in GOOD[:2]:
            conv.say(part)
            counts.append(conv.kind("teachback", phase="listening")["words"])
        assert counts == sorted(counts) and counts[0] > 5 and counts[1] > counts[0]
        assert len(conv.of("assistant_done")) == 1  # only the opening prompt was spoken
        assert not conv.of("notes")
    assert client.get("/api/notes").json() == []


def test_im_done_scores_it_with_objective_metrics_beats_and_brief_gentle_feedback(
    client: TestClient,
) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        start(conv)
        conv.kind("assistant_done")
        for part in GOOD:
            conv.say(part)
            conv.kind("teachback", phase="listening")
        conv.say("I'm done")
        conv.kind("teachback", phase="scoring")
        scored = conv.kind("teachback", phase="scored")
        conv.kind("mode", mode="capture")
        conv.kind("assistant_done")  # the feedback was spoken (the prompt's done was claimed above)

    m = scored["metrics"]
    assert m["word_count"] == sum(len(p.split()) for p in GOOD)
    assert m["wpm"] is None  # typed: no timings, so no pace claimed
    assert m["filler_count"] == 0 and m["sentences"]["count"] == 3
    assert set(scored["beats"]) == {"what", "how", "why", "impact"}
    assert scored["structure"] == 100.0 and all(b["present"] for b in scored["beats"].values())
    assert scored["rewrite"] is None or scored["rewrite"]["original"] in " ".join(GOOD)
    assert 2 <= len(scored["suggestions"]) <= 3
    spoken = conv.spoken()
    assert scored["well_done"] in spoken and scored["to_fix"] in spoken  # one done well, one to fix


def test_a_thin_explanation_misses_beats_and_scores_lower(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        start(conv)
        conv.say(
            "Um so indexes are kind of a thing that databases have for many different reasons and uses."
        )
        conv.kind("teachback", phase="listening")
        conv.say(
            "Basically they are, you know, used a lot in many places by many people for many things."
        )
        conv.kind("teachback", phase="listening")
        conv.say("done")
        scored = conv.kind("teachback", phase="scored")
    assert scored["structure"] < 100.0 and not all(b["present"] for b in scored["beats"].values())
    assert scored["metrics"]["filler_count"] >= 3  # um, basically, you know
    assert scored["metrics"]["filler_rate"] > 0 and "um" in scored["metrics"]["fillers"]
    assert scored["to_fix"]


def test_too_little_said_is_reported_not_scored(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        start(conv)
        conv.kind("assistant_done")  # let the opening prompt finish
        conv.say("It is a thing")
        conv.say("that's all")
        conv.kind("teachback", phase="too_short")
        conv.kind("mode", mode="capture")
        conv.kind("assistant_done")
        assert "a bit short to score" in conv.spoken()
    assert client.get("/api/stats").json()["articulation_trend"] == []


def test_cancelling_skips_scoring(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        start(conv)
        conv.say(GOOD[0])
        conv.say("never mind")
        conv.kind("teachback", phase="cancelled")
        conv.kind("mode", mode="capture")
    assert client.get("/api/stats").json()["articulation_trend"] == []


def test_the_buttons_do_what_the_spoken_commands_do(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.send(type="teachback_start", topic="why sleep matters")
        listening = conv.kind("teachback", phase="listening")
        assert listening["topic"] == "why sleep matters"
        for part in GOOD:
            conv.say(part)
        conv.send(type="teachback_done")
        assert conv.kind("teachback", phase="scored")["metrics"]["word_count"] > 30


def test_with_no_topic_it_suggests_one_from_the_track(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start()
        conv.send(type="teachback_start")
        topic = conv.kind("teachback", phase="listening")["topic"]
        assert topic == "how retrieval augmented generation works"


def test_a_score_lands_in_the_stats_trend_with_the_filler_rate(client: TestClient) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        start(conv)
        for part in GOOD:
            conv.say(part)
        conv.say("I'm done")
        conv.kind("teachback", phase="scored")
        conv.kind("mode", mode="capture")
    (point,) = client.get("/api/stats").json()["articulation_trend"]
    assert point["sessions"] == 1 and point["structure"] == 100.0 and point["filler_rate"] == 0.0
    assert point["wpm"] is None and 0 <= point["clarity"] <= 100


def test_teach_back_works_in_every_track_and_scores_are_not_filed_as_notes(
    client: TestClient,
) -> None:
    with client.websocket_connect("/ws/voice") as ws:
        conv = Conv(ws)
        conv.start("english")
        conv.say("teach-back on explaining my week")
        assert conv.kind("teachback", phase="listening")["topic"] == "explaining my week"


# ---- speech input: word timings from the transcriber ----


def deepgram(
    words: list[tuple[str, float, float]],
    text: str,
    *,
    final: bool = True,
    speech_final: bool = False,
) -> dict[str, Any]:
    return {
        "type": "Results",
        "is_final": final,
        "speech_final": speech_final,
        "channel": {
            "alternatives": [
                {
                    "transcript": text,
                    "confidence": 0.97,
                    "words": [
                        {"word": w.lower(), "punctuated_word": w, "start": s, "end": e}
                        for w, s, e in words
                    ],
                }
            ]
        },
    }


def test_the_transcriber_hands_over_word_timings_with_the_final_transcript() -> None:
    a = TranscriptAssembler()
    a.feed(deepgram([("Um,", 0.2, 0.5), ("an", 0.6, 0.7)], "Um, an", final=True))
    (event,) = a.feed(
        deepgram([("index", 3.0, 3.4), ("is", 3.5, 3.6)], "index is", final=True, speech_final=True)
    )
    assert event.final and event.text == "Um, an index is"
    assert event.words == [
        {"w": "Um,", "start": 0.2, "end": 0.5},
        {"w": "an", "start": 0.6, "end": 0.7},
        {"w": "index", "start": 3.0, "end": 3.4},
        {"w": "is", "start": 3.5, "end": 3.6},
    ]
    assert a.flush() == []  # nothing left over to leak into the next utterance


def test_word_timings_are_stored_with_the_utterance() -> None:
    async def go(db: Any, track: Any) -> list[dict[str, Any]] | None:
        session = await sessions_svc.create_session(db, track)
        from app.db.models import Speaker

        await sessions_svc.add_utterance(
            db,
            session.id,
            Speaker.user,
            "hello there",
            0.9,
            [{"w": "hello", "start": 0.0, "end": 0.4}, {"w": "there", "start": 0.5, "end": 0.8}],
        )
        fresh = await sessions_svc.get_session(db, session.id)
        assert fresh is not None
        return fresh.utterances[0].words

    assert run_db(go) == [
        {"w": "hello", "start": 0.0, "end": 0.4},
        {"w": "there", "start": 0.5, "end": 0.8},
    ]

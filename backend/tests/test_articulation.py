import asyncio
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.agent.schemas import BeatCheck, TeachBackScore
from app.llm.client import UsageTracker
from app.llm.fake import FakeLLM
from app.services import articulation as svc
from app.services.articulation import Segment, validate_score
from app.services.scoring import Word, compute_metrics
from tests.helpers import run_db

TRANSCRIPT = (
    "An index is a sorted structure that points at rows. "
    "It works by keeping keys in order so a search can jump straight to the right place. "
    "This matters because lookups stay fast even when the table is huge, which means queries finish in milliseconds."
)


def score(**over: Any) -> TeachBackScore:
    base: dict[str, Any] = {
        "what": BeatCheck(present=True, evidence="An index is a sorted structure"),
        "how": BeatCheck(present=True, evidence="keeping keys in order so a search can jump"),
        "why": BeatCheck(present=True, evidence="This matters because lookups stay fast"),
        "impact": BeatCheck(present=True, evidence="queries finish in milliseconds"),
        "clarity": 82,
        "clarity_reason": "Ordered and concrete.",
        "well_done": "You started with a clear definition",
        "to_fix": "Try a shorter closing sentence",
        "suggestions": [
            "Add an example.",
            "Pause between ideas.",
            "Say the takeaway first.",
            "Extra one",
        ],
        "weak_sentence": "This matters because lookups stay fast even when the table is huge, which means queries finish in milliseconds.",
        "rewrite": "Lookups stay fast even on a huge table, so queries finish in milliseconds.",
    }
    base.update(over)
    return TeachBackScore(**base)


def validated(s: TeachBackScore) -> svc.Feedback:
    return validate_score(
        s, topic="database indexes", transcript=TRANSCRIPT, metrics=compute_metrics([])
    )


def test_a_fully_evidenced_score_passes_through() -> None:
    fb = validated(score())
    assert fb.structure == 100.0 and fb.clarity == 82.0
    assert all(b.present for b in fb.beats.values())
    assert fb.rewrite and fb.rewrite.original.startswith("This matters because")
    assert len(fb.suggestions) == 3  # capped at three


def test_a_beat_without_quotable_evidence_does_not_count() -> None:
    fb = validated(
        score(impact=BeatCheck(present=True, evidence="it makes the app twenty times faster"))
    )
    assert fb.beats["impact"].present is False and fb.beats["impact"].evidence == ""
    assert fb.structure == 75.0


def test_a_beat_marked_missing_stays_missing_and_structure_is_the_share_present() -> None:
    fb = validated(score(why=BeatCheck(present=False), impact=BeatCheck(present=False)))
    assert fb.structure == 50.0 and not fb.beats["why"].present


def test_evidence_matching_ignores_case_and_punctuation() -> None:
    fb = validated(score(what=BeatCheck(present=True, evidence="an INDEX is a sorted structure!")))
    assert fb.beats["what"].present


def test_a_rewrite_of_a_sentence_the_learner_never_said_is_dropped() -> None:
    fb = validated(score(weak_sentence="Indexes are implemented as B-trees in most databases."))
    assert fb.rewrite is None


def test_spoken_feedback_is_one_thing_done_well_and_one_thing_to_fix() -> None:
    fb = validated(score())
    assert fb.spoken() == "You started with a clear definition. Try a shorter closing sentence."
    assert (
        validated(score(well_done="Nice start!", to_fix="Slow down?")).spoken()
        == "Nice start! Slow down?"
    )


def test_the_fake_model_scores_a_good_and_a_thin_explanation_differently() -> None:
    llm = FakeLLM(UsageTracker())
    good = asyncio.run(
        svc.score_teach_back(
            llm, topic="indexes", segments=[Segment(TRANSCRIPT, [])], track_slug="ai-eng"
        )
    )
    thin = asyncio.run(
        svc.score_teach_back(
            llm,
            topic="indexes",
            segments=[
                Segment(
                    "Indexes are kind of a thing that databases have for many different reasons and uses.",
                    [],
                )
            ],
            track_slug="ai-eng",
        )
    )
    assert good.structure == 100.0 and thin.structure < good.structure
    assert good.clarity > thin.clarity


def test_scoring_uses_the_word_timings_so_speech_gets_pace_and_pauses() -> None:
    words = [
        Word(w, i * 0.4 + (3.0 if i == 20 else 0), i * 0.4 + 0.3 + (3.0 if i == 20 else 0))
        for i, w in enumerate(TRANSCRIPT.split())
    ]
    fb = asyncio.run(
        svc.score_teach_back(
            FakeLLM(UsageTracker()),
            topic="indexes",
            segments=[Segment(TRANSCRIPT, words)],
            track_slug="ai-eng",
        )
    )
    assert fb.metrics.wpm is not None and 100 < fb.metrics.wpm < 160
    assert fb.metrics.long_pauses >= 1
    typed = asyncio.run(
        svc.score_teach_back(
            FakeLLM(UsageTracker()),
            topic="indexes",
            segments=[Segment(TRANSCRIPT, [])],
            track_slug="ai-eng",
        )
    )
    assert typed.metrics.wpm is None


def test_scores_are_stored_and_trend_by_local_day() -> None:
    fb = validated(score())

    async def go(db: Any, track: Any) -> list[Any]:
        for clarity, wpm in ((60.0, 120.0), (80.0, None)):
            f = fb.model_copy(update={"clarity": clarity})
            f.metrics = f.metrics.model_copy(update={"wpm": wpm})
            await svc.save_score(db, f, session_id=None)
        return await svc.trend(db, now=datetime.now(UTC), tz=ZoneInfo("UTC"))

    (point,) = run_db(go)
    assert point.sessions == 2 and point.clarity == 70.0 and point.structure == 100.0
    assert point.wpm == 120.0  # typed attempts have no wpm and are left out of the average


def test_an_empty_history_has_no_trend() -> None:
    async def go(db: Any, track: Any) -> list[Any]:
        return await svc.trend(db, now=datetime.now(UTC), tz=ZoneInfo("UTC"))

    assert run_db(go) == []


@pytest.mark.parametrize("value", [-5, 140])
def test_clarity_outside_zero_to_hundred_is_rejected_by_the_schema(value: int) -> None:
    with pytest.raises(ValueError):
        score(clarity=value)

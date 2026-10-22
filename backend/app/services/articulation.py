"""Scoring a teach-back: code-computed metrics + the model's structure scoring, validated."""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.prompts import load_prompt
from app.agent.schemas import BeatCheck, TeachBackScore
from app.db.models import ArticulationScore
from app.ingest.citations import normalize
from app.llm.client import LLMClient
from app.services.scoring import Metrics, Word, compute_metrics, words_from_text
from app.services.timeutil import local_date
from app.tracks import guidance_for

MIN_WORDS_TO_SCORE = 15
BEATS = ("what", "how", "why", "impact")


class Beat(BaseModel):
    present: bool
    evidence: str = ""


class Rewrite(BaseModel):
    original: str
    improved: str


class Feedback(BaseModel):
    """Everything stored in `articulation_scores.feedback` and shown on screen."""

    topic: str
    transcript: str
    metrics: Metrics
    beats: dict[str, Beat]
    clarity: float
    structure: float
    clarity_reason: str
    well_done: str
    to_fix: str
    suggestions: list[str]
    rewrite: Rewrite | None = None

    def spoken(self) -> str:
        """Brief and gentle: one thing done well, one thing to fix."""
        return f"{_sentence(self.well_done)} {_sentence(self.to_fix)}"


def _sentence(text: str) -> str:
    text = " ".join(text.split())
    return text if text.endswith((".", "!", "?")) else text + "."


def _in(text: str, transcript_norm: str) -> bool:
    n = normalize(text)
    return len(n.split()) >= 2 and n in transcript_norm


def validate_score(
    score: TeachBackScore, *, topic: str, transcript: str, metrics: Metrics
) -> Feedback:
    """Never trust the model: beats need quotable evidence, and the rewrite must be about a
    sentence the learner really said."""
    haystack = normalize(transcript)
    beats: dict[str, Beat] = {}
    for name in BEATS:
        check: BeatCheck = getattr(score, name)
        verified = check.present and _in(check.evidence, haystack)
        beats[name] = Beat(present=verified, evidence=check.evidence.strip() if verified else "")

    rewrite = None
    if _in(score.weak_sentence, haystack) and score.rewrite.strip():
        rewrite = Rewrite(original=score.weak_sentence.strip(), improved=score.rewrite.strip())

    present = sum(1 for b in beats.values() if b.present)
    return Feedback(
        topic=topic,
        transcript=transcript,
        metrics=metrics,
        beats=beats,
        clarity=float(min(100, max(0, score.clarity))),
        structure=present / len(BEATS) * 100,
        clarity_reason=score.clarity_reason.strip(),
        well_done=score.well_done.strip(),
        to_fix=score.to_fix.strip(),
        suggestions=[s.strip() for s in score.suggestions if s.strip()][:3],
        rewrite=rewrite,
    )


@dataclass
class Segment:
    text: str
    words: list[Word]


async def score_teach_back(
    llm: LLMClient,
    *,
    topic: str,
    segments: list[Segment],
    track_slug: str,
    session_id: uuid.UUID | None = None,
) -> Feedback:
    transcript = " ".join(s.text.strip() for s in segments).strip()
    words = [w for s in segments for w in (s.words or words_from_text(s.text))]
    metrics = compute_metrics(words, transcript)
    user = (
        f"TOPIC: {topic}\n"
        f"TRANSCRIPT:\n{transcript}\n\n"
        f"METRICS: {metrics.word_count} words"
        + (f", {metrics.wpm} words per minute" if metrics.wpm else "")
        + f", {metrics.filler_count} filler words, {metrics.long_pauses} long pauses, "
        f"average sentence {metrics.sentences.mean} words."
    )
    score = await llm.complete_structured(
        "deep",
        system=load_prompt("teach_back_score").text + guidance_for(track_slug, "teach_back"),
        user=user,
        schema=TeachBackScore,
        session_id=session_id,
    )
    return validate_score(score, topic=topic, transcript=transcript, metrics=metrics)


async def save_score(
    db: AsyncSession,
    feedback: Feedback,
    *,
    session_id: uuid.UUID | None,
    note_id: uuid.UUID | None = None,
) -> ArticulationScore:
    row = ArticulationScore(
        session_id=session_id,
        note_id=note_id,
        clarity=feedback.clarity,
        structure=feedback.structure,
        filler_rate=feedback.metrics.filler_rate,
        wpm=feedback.metrics.wpm,
        feedback=feedback.model_dump(mode="json"),
    )
    db.add(row)
    await db.commit()
    return row


@dataclass(frozen=True)
class TrendPoint:
    day: date
    clarity: float
    structure: float
    filler_rate: float
    wpm: float | None
    sessions: int


async def trend(
    db: AsyncSession, *, now: datetime, tz: ZoneInfo, days: int = 60
) -> list[TrendPoint]:
    """Per-day averages of teach-back scores (all tracks: articulation is one skill)."""
    rows = (
        await db.execute(
            select(ArticulationScore)
            .where(ArticulationScore.created_at >= now - timedelta(days=days))
            .order_by(ArticulationScore.created_at)
        )
    ).scalars()
    by_day: dict[date, list[ArticulationScore]] = defaultdict(list)
    for row in rows:
        by_day[local_date(row.created_at, tz)].append(row)

    def mean(values: list[float]) -> float:
        return sum(values) / len(values)

    points = []
    for day, items in sorted(by_day.items()):
        wpms = [r.wpm for r in items if r.wpm is not None]
        points.append(
            TrendPoint(
                day=day,
                clarity=round(mean([r.clarity for r in items]), 1),
                structure=round(mean([r.structure for r in items]), 1),
                filler_rate=round(mean([r.filler_rate for r in items]), 1),
                wpm=round(mean(wpms), 1) if wpms else None,
                sessions=len(items),
            )
        )
    return points


def feedback_from_row(row: ArticulationScore) -> dict[str, Any]:
    return dict(row.feedback)

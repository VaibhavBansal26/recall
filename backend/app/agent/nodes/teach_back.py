"""Teach-back: the learner explains something out loud; we keep the transcript, then score it."""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.agent.deps import AgentDeps
from app.db.models import ArticulationScore
from app.services import accuracy as accuracy_svc
from app.services import articulation as articulation_svc
from app.services.articulation import MIN_WORDS_TO_SCORE, Feedback, Segment
from app.services.reference import Reference
from app.services.scoring import Word
from app.tracks import get_track_config
from app.voice.events import (
    TeachBackAccuracy,
    TeachBackBeat,
    TeachBackContradiction,
    TeachBackEvent,
    TeachBackRewrite,
)


def words_from_stt(raw: list[dict[str, Any]] | None) -> list[Word]:
    return [Word(str(w["w"]), float(w["start"]), float(w["end"])) for w in raw or []]


def suggest_topic(track: str) -> str:
    ideas = get_track_config(track).teach_back_ideas
    return ideas[0].removeprefix("Explain ").strip() if ideas else "something you know well"


@dataclass
class TeachBackSession:
    deps: AgentDeps
    session_id: uuid.UUID
    track: str
    topic: str
    segments: list[Segment] = field(default_factory=list)
    # Evaluate mode: the explanation is also checked against these notes / source text.
    reference: Reference | None = None
    started: float = field(default_factory=time.perf_counter)

    @property
    def word_count(self) -> int:
        return sum(len(s.text.split()) for s in self.segments)

    def add(self, text: str, raw_words: list[dict[str, Any]] | None) -> TeachBackEvent:
        self.segments.append(Segment(text, words_from_stt(raw_words)))
        return self.listening()

    def listening(self) -> TeachBackEvent:
        return TeachBackEvent(
            phase="listening",
            topic=self.topic,
            words=self.word_count,
            ideas=get_track_config(self.track).teach_back_ideas,
            checking=self.reference.about() if self.reference and not self.reference.empty else "",
        )

    async def finish(
        self, *, note_id: uuid.UUID | None
    ) -> tuple[
        TeachBackEvent, Feedback | None, ArticulationScore | None, accuracy_svc.Accuracy | None
    ]:
        """Score what was said. Too little to judge is reported instead of scored."""
        if self.word_count < MIN_WORDS_TO_SCORE:
            return (
                TeachBackEvent(phase="too_short", topic=self.topic, words=self.word_count),
                None,
                None,
                None,
            )
        feedback = await articulation_svc.score_teach_back(
            self.deps.llm,
            topic=self.topic,
            segments=self.segments,
            track_slug=self.track,
            session_id=self.session_id,
        )
        async with self.deps.sessionmaker() as db:
            row = await articulation_svc.save_score(
                db, feedback, session_id=self.session_id, note_id=note_id
            )
        accuracy = None
        if self.reference is not None and not self.reference.empty:
            accuracy = await accuracy_svc.check(
                self.deps.llm,
                topic=self.topic,
                transcript=" ".join(s.text for s in self.segments),
                reference=self.reference,
                session_id=self.session_id,
            )
        return scored_event(feedback, accuracy), feedback, row, accuracy


def scored_event(fb: Feedback, accuracy: accuracy_svc.Accuracy | None = None) -> TeachBackEvent:
    return TeachBackEvent(
        accuracy=(
            TeachBackAccuracy(
                against=accuracy.against,
                covered=accuracy.covered,
                missed=accuracy.missed,
                contradicted=[
                    TeachBackContradiction(said=c.said, reference=c.reference)
                    for c in accuracy.contradicted
                ],
                verdict=accuracy.verdict,
            )
            if accuracy
            else None
        ),
        phase="scored",
        topic=fb.topic,
        words=fb.metrics.word_count,
        metrics=fb.metrics,
        beats={
            k: TeachBackBeat(present=b.present, evidence=b.evidence) for k, b in fb.beats.items()
        },
        clarity=fb.clarity,
        structure=fb.structure,
        clarity_reason=fb.clarity_reason,
        well_done=fb.well_done,
        to_fix=fb.to_fix,
        suggestions=fb.suggestions,
        rewrite=(
            TeachBackRewrite(original=fb.rewrite.original, improved=fb.rewrite.improved)
            if fb.rewrite
            else None
        ),
    )

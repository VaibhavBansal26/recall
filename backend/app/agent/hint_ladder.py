"""The hint ladder for one quiz question, as a small state machine.

Tier 0 = question asked, no hint. 1 = nudge (point at the area, no answer). 2 = partial
(reveal the first piece). 3 = reveal and explain. A correct answer at any tier ends the
question at that tier; a wrong answer or "I forgot" moves one tier up; tier 3 always ends it.
"""

from dataclasses import dataclass
from typing import Literal

from fsrs import Rating

MAX_TIER = 3
EASY_WITHIN_MS = 6000  # correct, unaided and quick (includes the time the question took to say)


@dataclass(frozen=True)
class Step:
    action: Literal["advance", "finish"]
    tier: int  # advance: the tier to show next. finish: the tier used for grading.


@dataclass
class HintLadder:
    tier: int = 0
    finished: bool = False

    def on_answer(self, correct: bool) -> Step:
        return self._finish() if correct else self.on_give_up()

    def on_give_up(self) -> Step:
        """Wrong answer, "I forgot", or an explicit request for a hint."""
        if self.tier >= MAX_TIER:
            return self._finish()
        self.tier += 1
        return Step("advance", self.tier)

    def _finish(self) -> Step:
        self.finished = True
        return Step("finish", self.tier)


def rating_for(hint_tier: int, latency_ms: int | None = None) -> Rating:
    """Correct unaided = Good (Easy if quick), tier 1 = Hard, tier 2 or 3 = Again."""
    if hint_tier == 0:
        if latency_ms is not None and latency_ms <= EASY_WITHIN_MS:
            return Rating.Easy
        return Rating.Good
    return Rating.Hard if hint_tier == 1 else Rating.Again

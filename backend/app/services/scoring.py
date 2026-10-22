"""Articulation metrics, computed in code (never by the LLM): pace, fillers, pauses, sentences.

The model only scores what cannot be counted (structure and clarity). Everything here is
deterministic, so the same transcript always gives the same numbers.
"""

import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import BaseModel

LONG_PAUSE_S = 1.5  # a gap this long between words counts as a long pause
MIN_WPM_SECONDS = 3.0  # too short a span makes words-per-minute meaningless
MIN_WPM_WORDS = 10
SHORT_SENTENCE_WORDS = 8
LONG_SENTENCE_WORDS = 20

_SIMPLE_FILLERS = {"um", "umm", "uh", "uhh", "uhm", "er", "erm", "hmm", "basically", "actually"}
# Words before "like" that make it a verb or comparison ("I like", "looks like"), not a filler.
_LIKE_VERB_BEFORE = {
    "i", "we", "you", "they", "he", "she", "would", "do", "did", "dont", "doesnt", "didnt",
    "look", "looks", "looked", "feel", "feels", "felt", "sound", "sounds", "seem", "seems",
    "something", "anything", "nothing", "more", "most", "much", "exactly", "very", "quite",
    "just", "what", "how", "why", "who",
}  # fmt: skip
_LIKE_COMPARISON_AFTER = {
    "a", "an", "the", "this", "that", "these", "those", "my", "your", "his", "her", "our",
    "their", "some", "any", "to",
}  # fmt: skip
_LIKE_LEAD_IN = {
    "was",
    "is",
    "were",
    "are",
    "its",
    "thats",
    "so",
    "and",
    "but",
    "be",
    "then",
    "because",
}


@dataclass(frozen=True)
class Word:
    text: str
    start: float | None = None  # seconds; None for typed answers
    end: float | None = None


class SentenceStats(BaseModel):
    count: int
    mean: float
    median: float
    longest: int
    short: int  # up to 8 words
    medium: int  # 9 to 20
    long: int  # over 20
    punctuated: bool  # False when no sentence breaks were found (counts are then one run-on)


class Pause(BaseModel):
    after_word: str
    seconds: float


class Metrics(BaseModel):
    word_count: int
    duration_s: float | None  # None when there are no word timings
    wpm: float | None
    filler_count: int
    filler_rate: float  # per 100 words
    fillers: dict[str, int]
    long_pauses: int
    longest_pause_s: float
    pauses: list[Pause]  # the longest few
    sentences: SentenceStats


def _norm(token: str) -> str:
    return re.sub(r"[^a-z0-9']", "", token.lower()).replace("'", "")


def count_fillers(tokens: Sequence[str]) -> dict[str, int]:
    """Filler words and phrases by kind. `tokens` keep their punctuation (commas help tell
    a filler "like" from a real one)."""
    norm = [_norm(t) for t in tokens]
    counts: dict[str, int] = {}

    def add(kind: str) -> None:
        counts[kind] = counts.get(kind, 0) + 1

    for i, word in enumerate(norm):
        raw = tokens[i]
        prev_raw = tokens[i - 1] if i else ""
        nxt = norm[i + 1] if i + 1 < len(norm) else ""
        prev = norm[i - 1] if i else ""
        if word in _SIMPLE_FILLERS:
            add("um" if word in {"um", "umm", "uhm"} else "uh" if word in {"uh", "uhh"} else word)
        elif word == "you" and nxt == "know":
            offset_raw = tokens[i + 1] if i + 1 < len(tokens) else ""
            # "you know" as a filler is set off by commas or ends the clause; "do you know how"
            # is a real question and is not counted.
            if (
                prev_raw.endswith(",")
                or raw.endswith(",")
                or offset_raw.endswith((",", ".", "?", "!"))
            ):
                add("you know")
        elif word == "like":
            comma = prev_raw.endswith(",") or raw.endswith(",") or raw.startswith(",")
            lead_in = prev in _LIKE_LEAD_IN and nxt not in _LIKE_COMPARISON_AFTER
            if (comma or lead_in) and prev not in _LIKE_VERB_BEFORE:
                add("like")
    return counts


def split_sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def sentence_stats(text: str) -> SentenceStats:
    sentences = split_sentences(text)
    lengths = [len(s.split()) for s in sentences] or [0]
    punctuated = bool(re.search(r"[.!?]", text))
    return SentenceStats(
        count=len(sentences),
        mean=round(statistics.fmean(lengths), 1),
        median=float(statistics.median(lengths)),
        longest=max(lengths),
        short=sum(1 for n in lengths if n <= SHORT_SENTENCE_WORDS),
        medium=sum(1 for n in lengths if SHORT_SENTENCE_WORDS < n <= LONG_SENTENCE_WORDS),
        long=sum(1 for n in lengths if n > LONG_SENTENCE_WORDS),
        punctuated=punctuated,
    )


def compute_metrics(words: Sequence[Word], text: str | None = None) -> Metrics:
    """Metrics for a transcript. `words` may be untimed (typed); `text` overrides the sentence
    source when the words carry no punctuation."""
    tokens = [w.text for w in words]
    n = len(tokens)
    fillers = count_fillers(tokens)
    filler_count = sum(fillers.values())

    timed = [w for w in words if w.start is not None and w.end is not None]
    duration: float | None = None
    wpm: float | None = None
    pauses: list[Pause] = []
    if len(timed) >= 2:
        duration = round(timed[-1].end - timed[0].start, 2)  # type: ignore[operator]
        if duration >= MIN_WPM_SECONDS and n >= MIN_WPM_WORDS:
            wpm = round(n / duration * 60, 1)
        for before, after in zip(timed, timed[1:], strict=False):
            gap = after.start - before.end  # type: ignore[operator]
            if gap >= LONG_PAUSE_S:
                pauses.append(Pause(after_word=before.text, seconds=round(gap, 2)))
    pauses.sort(key=lambda p: -p.seconds)

    return Metrics(
        word_count=n,
        duration_s=duration,
        wpm=wpm,
        filler_count=filler_count,
        filler_rate=round(filler_count / n * 100, 1) if n else 0.0,
        fillers=fillers,
        long_pauses=len(pauses),
        longest_pause_s=pauses[0].seconds if pauses else 0.0,
        pauses=pauses[:5],
        sentences=sentence_stats(text if text is not None else " ".join(tokens)),
    )


def words_from_text(text: str) -> list[Word]:
    """Untimed words for a typed answer."""
    return [Word(t) for t in text.split()]

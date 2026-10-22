"""Confusion detection: phrases, the same question asked twice, and (in the connection) silence."""

import re

_PHRASES = [
    r"^\s*(wait|hold on|hang on)\b",
    r"\bi\s*(don'?t|do not|didn'?t|did not)\s*(really\s*)?(get|understand|follow)\b",
    r"\bwhat do you mean\b",
    r"\bi'?m\s+(so\s+)?(confused|lost)\b",
    r"\b(dumb|break|simplify)\b.*\b(down|it)\b",
    r"\bsimpl(er|y|ify)\b",
    r"\b(explain|say|go (over|through)) (that|it|this)? ?again\b",
    r"\b(that|this|it)\s+(doesn'?t|does not)\s+make sense\b",
    r"\bin (plain|simple) (english|words|terms)\b",
]
_PHRASE_RES = [re.compile(p, re.IGNORECASE) for p in _PHRASES]

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "do", "does", "did", "of", "to", "in", "on",
    "and", "or", "it", "that", "this", "me", "my", "you", "can", "could", "please", "what",
    "how", "why", "so", "um", "uh",
}  # fmt: skip
_QUESTION_START = re.compile(
    r"^\s*(what|how|why|when|where|who|which|can|could|does|do|is|are|explain|tell)\b", re.I
)


def detect_phrase(text: str) -> str | None:
    """Name of the confusion phrase found in `text`, or None."""
    for pattern in _PHRASE_RES:
        if m := pattern.search(text):
            return m.group(0).strip().lower()
    return None


def _tokens(text: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return frozenset(w for w in words if w not in _STOPWORDS)


def looks_like_question(text: str) -> bool:
    return text.strip().endswith("?") or bool(_QUESTION_START.match(text))


class ConfusionTracker:
    """Remembers this session's questions so a repeat counts as confusion."""

    def __init__(self, similarity: float = 0.8) -> None:
        self._similarity = similarity
        self._questions: list[frozenset[str]] = []

    def check(self, text: str) -> str | None:
        """Trigger name ("phrase: ..." or "repeated question") if this turn shows confusion."""
        if phrase := detect_phrase(text):
            return f"phrase: {phrase}"
        if looks_like_question(text):
            tokens = _tokens(text)
            if tokens:
                for earlier in self._questions:
                    overlap = len(tokens & earlier) / len(tokens | earlier)
                    if overlap >= self._similarity:
                        return "repeated question"
                self._questions.append(tokens)
        return None

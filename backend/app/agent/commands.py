# ruff: noqa: E501
"""Spoken commands for notebooks, discussions and recitation. Pure functions, no I/O.

"Create a new notes file for binary search under dsa"   -> make the notebook, file notes there
"Open my hash map notes" / "close the notebook"          -> switch the notebook new notes go to
"Let's discuss designing a URL shortener"                -> a worked discussion (solutions track)
"Start reciting my binary search notes"                  -> explain each note and ask in between
"Draw the architecture"                                  -> an overview diagram of the notebook
"""

import re
from dataclasses import dataclass, field

# What the learner might call each track. Longest phrases first so "system design" beats "design".
TRACK_ALIASES: list[tuple[str, str]] = [
    ("data structures and algorithms", "dsa"),
    ("data structures", "dsa"),
    ("algorithms", "dsa"),
    ("dsa", "dsa"),
    ("ai engineering", "ai-eng"),
    ("ai concepts", "ai-eng"),
    ("ai eng", "ai-eng"),
    ("ai", "ai-eng"),
    ("machine learning", "ai-eng"),
    ("system design", "solutions"),
    ("solutions", "solutions"),
    ("solution", "solutions"),
    ("spoken english", "english"),
    ("english", "english"),
]
_ALIAS_RX = "|".join(re.escape(a) for a, _ in sorted(TRACK_ALIASES, key=lambda p: -len(p[0])))
_TRACK_TAIL = r"(?:\s+(?:folder|track|section|directory|category|notes))?"

NOTEBOOK_WORDS = r"(?:notes?|notebooks?|files?|folders?|directory|directories)"


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


def track_for(phrase: str) -> str | None:
    wanted = phrase.strip().lower()
    for alias, slug in TRACK_ALIASES:
        if alias == wanted:
            return slug
    return None


@dataclass(frozen=True)
class NotebookCommand:
    kind: str  # "new" | "open" | "close"
    names: tuple[str, ...] = ()
    track: str | None = None


@dataclass(frozen=True)
class DiscussCommand:
    kind: str  # "start" | "wrap" | "end"
    topic: str | None = None
    track: str | None = "solutions"


@dataclass(frozen=True)
class ReciteCommand:
    topic: str | None = None
    track: str | None = None


@dataclass
class _Parsed:
    names: list[str] = field(default_factory=list)
    track: str | None = None


_LEAD = r"^\W*(?:(?:ok(?:ay)?|alright|please|hey|so|now|can you|could you|i want to|i'd like to|i would like to|let'?s)[, ]+)*"

_NEW = _rx(
    _LEAD
    + r"(?:create|make|start|add|begin|set up|open)\s+(?:me\s+)?(?:a\s+|an\s+|some\s+|one\s+)?"
    r"(?:\d+\s+)?(?:new\s+)?(?:\w+\s+)?" + NOTEBOOK_WORDS + r"(?:\s+file)?\s+"
    r"(?:for|on|about|called|named|titled|to cover|covering)\s+(?P<rest>.+?)[.?!]?\s*$"
)
# "under dsa create a new note for binary search"
_NEW_TRACK_FIRST = _rx(
    r"^\W*(?:ok(?:ay)?[, ]+)?(?:under|in|inside|within)\s+(?:the\s+)?(?P<track>"
    + _ALIAS_RX
    + r")"
    + _TRACK_TAIL
    + r"[, ]+(?:create|make|add|start)\s+(?:a\s+|an\s+|some\s+)?(?:new\s+)?(?:notes?|notebooks?|files?)"
    r"(?:\s+file)?\s+(?:for|on|about|called|named)\s+(?P<rest>.+?)[.?!]?\s*$"
)
_TRAILING_TRACK = _rx(
    r"[, ]+(?:under|in|inside|within|for|to)\s+(?:the\s+)?(?P<track>"
    + _ALIAS_RX
    + r")"
    + _TRACK_TAIL
    + r"\s*$"
)
_OPEN = _rx(
    r"^\W*(?:(?:ok(?:ay)?|please|now|so)[, ]+)*(?:open|switch to|go to|go back to|back to|continue|"
    r"resume|add (?:this |these |it |them )?to)\s+(?:my\s+|the\s+)?(?P<name>.+?)\s+"
    + NOTEBOOK_WORDS
    + r"(?:\s+(?:in|under)\s+(?:the\s+)?(?P<track>"
    + _ALIAS_RX
    + r"))?[.?!]?\s*$"
)
_CLOSE = _rx(
    r"^\W*(?:(?:ok(?:ay)?|please|now)[, ]+)*(?:close|leave|exit|finish|done with)\s+"
    r"(?:the\s+|this\s+|my\s+)?" + NOTEBOOK_WORDS + r"\W*$"
)

_DISCUSS_START = _rx(
    _LEAD + r"(?:discuss|solve|design|work through|go through|talk through|think through|"
    r"practi[sc]e|do)\s+(?:a\s+|an\s+|the\s+|this\s+|about\s+)?(?P<topic>.+?)[.?!]?\s*$"
)
_DISCUSS_NOUN = _rx(
    r"\b(?:system design|design)\s+(?:discussion|session|question|problem|interview)\b"
    r"|\b(?:discussion|session|question|problem)\b.*\b(?:system design)\b"
)
_NEW_DISCUSSION_WORDS = _rx(
    r"\b(?:where we|in which we|so we can|to)\s+(?:discuss|solve|work through)\b|"
    r"\bsystem design\b|\bdiscuss(?:ion)?\b"
)
_WRAP = _rx(
    r"^\W*(?:(?:ok(?:ay)?|so|now|alright)[, ]+)*(?:wrap (?:it |this )?up|summari[sz]e(?: it| this| the discussion)?|"
    r"evaluate(?: it| this| my (?:design|solution|answer))?|give me (?:the |your )?(?:evaluation|verdict|summary)|"
    r"how did i do|that'?s (?:my|the) (?:final )?(?:design|answer|solution)|i'?m (?:done|finished)|"
    r"let'?s (?:wrap up|finish|conclude)|finalise|finalize)\W*$"
)
_DISCUSS_END = _rx(
    r"^\W*(?:(?:ok(?:ay)?|so|now)[, ]+)*(?:stop|exit|leave|end|quit|cancel|never ?mind|forget it)"
    r"(?:\s+(?:the\s+|this\s+)?(?:discussion|session|design|problem))?\W*$"
)

_RECITE = _rx(
    _LEAD
    + r"(?:start\s+|begin\s+)?(?:reciting|recite|revis(?:e|ing)|go over|go through|run through|"
    r"explain and quiz me on|teach me)\s+(?:me\s+)?(?:the\s+|my\s+)?"
    r"(?:notes?|notebooks?|files?|folders?)?(?:\s*(?:on|about|for|in|from|of))?\s*(?P<topic>.*?)[.?!]?\s*$"
)
_RECITE_STRICT = _rx(r"\brecit(?:e|ing|ation)\b")
_DRAW = _rx(
    r"^\W*(?:(?:ok(?:ay)?|please|now|so|can you|could you)[, ]+)*(?:draw|show|build|make|generate|create|give me)"
    r"\s+(?:me\s+)?(?:the\s+|an?\s+)?(?:(?:architecture|system|overall|full|whole|high[- ]level|final)\s+)*"
    r"(?:diagram|architecture|picture)(?:\s+(?:of|for)\s+(?:it|this|the (?:design|system|notes?)))?\W*$"
)


def split_names(rest: str) -> list[str]:
    """ "binary search and hash map" or "binary, hashmap" -> one name per file."""
    parts = re.split(r"\s*(?:,|;|&|\band\b|\bplus\b)\s*", rest)
    out: list[str] = []
    for part in parts:
        part = re.sub(r"^(?:the|a|an)\s+", "", part.strip(" .,:;\"'"), flags=re.IGNORECASE)
        if part and part.lower() not in {n.lower() for n in out}:
            out.append(part)
    return out


def _with_track(rest: str) -> _Parsed:
    parsed = _Parsed()
    if m := _TRAILING_TRACK.search(rest):
        parsed.track = track_for(m.group("track"))
        rest = rest[: m.start()]
    parsed.names = split_names(rest)
    return parsed


def parse_notebook(text: str) -> NotebookCommand | None:
    if _CLOSE.match(text):
        return NotebookCommand("close")
    if m := _NEW_TRACK_FIRST.match(text):
        names = split_names(m.group("rest"))
        return NotebookCommand("new", tuple(names), track_for(m.group("track"))) if names else None
    if m := _NEW.match(text):
        parsed = _with_track(m.group("rest"))
        if parsed.names:
            return NotebookCommand("new", tuple(parsed.names), parsed.track)
    if m := _OPEN.match(text):
        name = m.group("name").strip()
        if name and name.lower() not in {"the", "my", "this", "that", "new"}:
            return NotebookCommand("open", (name,), track_for(m.group("track") or ""))
    return None


def is_discussion_request(text: str) -> bool:
    """A "create new notes ..." request that is really a worked discussion."""
    return bool(_NEW_DISCUSSION_WORDS.search(text))


def parse_discuss(text: str) -> DiscussCommand | None:
    """Start a worked discussion, e.g. "let's discuss designing a rate limiter"."""
    if m := _NEW.match(text):
        if is_discussion_request(text):
            return DiscussCommand("start", _discussion_topic(m.group("rest")))
    if _DISCUSS_NOUN.search(text) and (
        m := re.search(r"\b(?:on|about|for|of)\s+(.+?)[.?!]?\s*$", text, re.IGNORECASE)
    ):
        return DiscussCommand("start", _discussion_topic(m.group(1)))
    if m := _DISCUSS_START.match(text):
        topic = m.group("topic")
        # "do my notes", "go through my notes" are recitation, not a discussion.
        if re.match(r"^(?:my\s+|the\s+)?(?:notes?|notebooks?|files?)\b", topic, re.IGNORECASE):
            return None
        if len(topic.split()) >= 2 and re.search(
            r"\b(?:discuss|solve|design|work through|talk through|think through)\b", text, re.I
        ):
            return DiscussCommand("start", _discussion_topic(topic))
    return None


GENERIC_TOPICS = {
    "system design", "design", "question", "problem", "it", "this", "that", "a problem",
    "a question", "the question", "a design", "something",
}  # fmt: skip


def is_generic_topic(topic: str) -> bool:
    return topic.strip(" .,").lower() in GENERIC_TOPICS


def _discussion_topic(topic: str) -> str:
    """ "system design where we discuss and solve the question" -> "system design"."""
    topic = re.split(r"\s+(?:where|in which|so)\s+(?:we|i)\b", topic, maxsplit=1)[0]
    topic = re.sub(r"^(?:a|an|the)\s+", "", topic.strip(" .,"), flags=re.IGNORECASE)
    topic = re.sub(r"\s+(?:question|problem|discussion|session)$", "", topic, flags=re.IGNORECASE)
    return topic.strip(" .,") or "system design"


def problem_from(text: str) -> str:
    """A short title from the first thing the learner says about a generic discussion."""
    text = re.sub(
        r"^\W*(?:ok(?:ay)?[, ]+)?(?:(?:let'?s|i want to|i'd like to|can we|please)\s+)*"
        r"(?:discuss|design|solve|work on|talk about|do)\s+(?:a\s+|an\s+|the\s+)?",
        "",
        text.strip(),
        flags=re.IGNORECASE,
    )
    words = text.split()[:8]
    return " ".join(words).strip(" .,?!") or "System design"


def discuss_followup(text: str) -> str | None:
    """Inside a discussion: "wrap" (evaluate it), "end" (leave it), else None (a normal turn)."""
    if _WRAP.match(text):
        return "wrap"
    if _DISCUSS_END.match(text):
        return "end"
    return None


def parse_recite(text: str) -> ReciteCommand | None:
    m = _RECITE.match(text)
    if m is None:
        return None
    # "go over"/"go through"/"teach me" are only recitation when notes are named: "go through my
    # notes on X" is, "go through the problem" is not.
    named = re.search(r"\b(?:notes?|notebooks?|files?|folders?)\b", text, re.IGNORECASE)
    if not _RECITE_STRICT.search(text) and not named and not re.search(r"\brevis", text, re.I):
        return None
    topic = m.group("topic").strip(" .,")
    track = None
    if tail := _TRAILING_TRACK.search(" " + topic) if topic else None:
        track = track_for(tail.group("track"))
        topic = topic[: max(0, tail.start() - 1)].strip(" .,")
    topic = re.sub(r"^(?:the|my|a|an)\s+", "", topic, flags=re.IGNORECASE)
    topic = re.sub(r"\s+(?:notes?|notebooks?|files?|folders?)$", "", topic, flags=re.IGNORECASE)
    if topic.lower() in {"", "it", "them", "this", "that", "these", "those", "all", "everything"}:
        topic = ""
    return ReciteCommand(topic or None, track)


def is_draw(text: str) -> bool:
    return bool(_DRAW.match(text))


_SIDE_QUESTION = _rx(
    r"^\W*(?:(?:ok(?:ay)?|wait|sorry|hold on|actually|so|and|but|hmm+|um+)[, ]+)*"
    r"(?:what|why|how|when|where|who|which|can you|could you|can i ask|may i ask|explain|"
    r"tell me|what do you mean|i have a question|quick question)\b"
)
_CONTROL = _rx(
    r"\b(?:repeat|again|slow(?:er)?|faster|speed up|skip|next|continue|go on|stop|hint|"
    r"what was the question|say that again|go back)\b"
)


def is_side_question(text: str) -> bool:
    """Something the learner asks in the middle of a recitation (as opposed to an answer to the
    check question, or a control word such as "next" or "repeat that")."""
    if len(text.split()) < 2 or _CONTROL.search(text):
        return False
    return bool(_SIDE_QUESTION.match(text)) or (
        text.strip().endswith("?") and len(text.split()) >= 4
    )

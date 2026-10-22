"""Turn router: which mode is this user turn for?

Obvious commands are matched by rules (instant, no LLM call, so they never add latency).
Only an unmatched question falls back to the fast model; everything else is capture.
"""

import enum
import re
import uuid
from dataclasses import dataclass

from pydantic import BaseModel

from app.agent.prompts import load_prompt
from app.llm.client import LLMClient


class Mode(enum.StrEnum):
    capture = "capture"
    explain = "explain"
    read_back = "read_back"
    recall_quiz = "recall_quiz"
    teach_back = "teach_back"
    ingest_review = "ingest_review"
    chitchat = "chitchat"


@dataclass(frozen=True)
class Route:
    mode: Mode
    topic: str | None = None
    command: str | None = None  # a mode-specific control word, e.g. "next", "hint", "start"


class RouteDecision(BaseModel):
    mode: Mode
    topic: str | None = None


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


_QUIZ_START = _rx(r"\b(quiz me|test me|ask me (some )?questions|what'?s due|review (my|what))\b")
_QUIZ_TOPIC = _rx(r"\b(?:quiz me|test me|questions)\s+(?:on|about)\s+(.+?)[.?!]?\s*$")
_READ_BACK = _rx(
    r"\bread\s+(?:me\s+)?(?:back\s+)?(?:my\s+)?(?:notes?\s+)?(?:on|about)\s+(.+?)[.?!]?\s*$"
)
_READ_BACK_ANY = _rx(r"\bread\s+(?:me\s+)?(?:back\s+)?my\s+notes\b")
_EXPLAIN = _rx(
    r"^\s*(?:can you |could you |please )?(?:explain|tell me about|walk me through|"
    r"what is|what'?s|what are|how does|how do|how is|why does|why do|why is)\s+(.+?)[.?!]?\s*$"
)

_INGEST_START = _rx(
    r"\b(what did you (file|add)|what'?s new|any new (material|sources?|notes)|"
    r"review (the )?(new )?(material|sources?)|what (was|got) filed|new material)\b"
)
_INGEST_COMMANDS = [
    ("end", _rx(r"\b(later|not now|stop|skip|leave it|cancel)\b")),
    ("undo", _rx(r"\b(no|undo|remove|discard|reject|get rid)\b")),
    (
        "approve",
        _rx(r"\b(yes|yeah|yep|approve|confirm|keep|accept|looks good|sounds good|go ahead)\b"),
    ),
]

_QUIZ_COMMANDS = [
    ("end", _rx(r"\b(stop|end|quit|exit|that'?s enough|no more)\b")),
    ("skip", _rx(r"\b(skip|pass|next question)\b")),
    ("forgot", _rx(r"\b(i forgot|forgot|i don'?t (know|remember)|no idea|not sure|blank)\b")),
    ("hint", _rx(r"\b(hint|clue|help me|give me a nudge)\b")),
]
_READ_COMMANDS = [
    ("stop", _rx(r"\b(stop|enough|that'?s enough|end)\b")),
    ("slower", _rx(r"\bslow(er)?\b")),
    ("faster", _rx(r"\b(faster|speed up|quicker)\b")),
    ("repeat", _rx(r"\b(repeat|again|say that again)\b")),
    ("skip", _rx(r"\bskip\b")),
    ("next", _rx(r"\b(next|continue|go on|keep going|carry on)\b")),
]


_DEICTIC = {"this", "that", "it", "these", "those", "everything", "all", "what i said"}


def _clean_topic(topic: str | None) -> str | None:
    """Drop "this"/"that" (not a subject) and the trailing "work" of "how does X work"."""
    if topic is None or topic.strip().lower() in _DEICTIC:
        return None
    return re.sub(r"\s+works?$", "", topic.strip(), flags=re.IGNORECASE) or None


def route_by_rules(text: str, current: Mode) -> Route | None:
    """A decisive route from the words alone, or None when the rules cannot tell."""
    if current == Mode.recall_quiz:
        for command, pattern in _QUIZ_COMMANDS:
            if pattern.search(text) and len(text.split()) <= 8:
                return Route(Mode.recall_quiz, command=command)
        return Route(Mode.recall_quiz, command="answer")  # sticky: this is an answer

    if current == Mode.ingest_review:
        for command, pattern in _INGEST_COMMANDS:
            if pattern.search(text) and len(text.split()) <= 8:
                return Route(Mode.ingest_review, command=command)
        return Route(Mode.ingest_review, command="repeat")

    if current == Mode.read_back:
        for command, pattern in _READ_COMMANDS:
            if pattern.search(text) and len(text.split()) <= 6:
                return Route(Mode.read_back, command=command)

    if _INGEST_START.search(text):
        return Route(Mode.ingest_review, command="start")
    if m := _READ_BACK.search(text):
        return Route(Mode.read_back, topic=_clean_topic(m.group(1)), command="start")
    if _READ_BACK_ANY.search(text):
        return Route(Mode.read_back, command="start")
    if _QUIZ_START.search(text):
        topic = _QUIZ_TOPIC.search(text)
        return Route(
            Mode.recall_quiz,
            topic=_clean_topic(topic.group(1)) if topic else None,
            command="start",
        )
    if m := _EXPLAIN.match(text):
        return Route(Mode.explain, topic=_clean_topic(m.group(1)))
    return None


async def route_turn(
    llm: LLMClient, text: str, current: Mode, session_id: uuid.UUID | None = None
) -> Route:
    route = route_by_rules(text, current)
    if route is not None:
        return route
    if not text.strip().endswith("?"):
        return Route(Mode.capture)  # the common case: the learner is explaining, keep listening
    decision = await llm.complete_structured(
        "fast",
        system=load_prompt("router").text,
        user=text,
        schema=RouteDecision,
        session_id=session_id,
    )
    # Teach-back has no node yet; treat it as the nearest working mode.
    if decision.mode == Mode.teach_back:
        return Route(Mode.capture)
    return Route(decision.mode, topic=decision.topic)

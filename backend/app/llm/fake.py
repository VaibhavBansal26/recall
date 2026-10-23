"""Deterministic stand-in for the LLM so everything runs and tests without API keys."""

import asyncio
import re
import uuid
from collections.abc import AsyncIterator

from app.agent.router import Mode, RouteDecision
from app.agent.schemas import (
    BeatCheck,
    CandidateNote,
    DiagramDraft,
    DiscussionSummary,
    DraftedNotes,
    ExtractedNotes,
    LinkProposal,
    LinkProposals,
    MergeResult,
    QuizTurn,
    ReciteExplain,
    ReviewDraft,
    ReviewDrafts,
    SourceCitation,
    SourceNote,
    SourceNotes,
    TeachBackScore,
    TrackClassification,
    WalkthroughDraft,
    WalkthroughStep,
    WhyMatters,
)
from app.llm.client import LLMClient, ModelKind, T, UsageTracker

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _field(user: str, key: str) -> str:
    """Value of a `KEY: value` field in a multi-line prompt (up to the next ALL-CAPS key)."""
    m = re.search(rf"^{re.escape(key)}:[ \t]*(.*?)(?=^[A-Z][A-Z ]+:|\Z)", user, re.S | re.M)
    return m.group(1).strip() if m else ""


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 4}


def _q(text: str) -> str:
    return text.replace('"', "'")


def _fake_teach_back(user: str) -> TeachBackScore:
    transcript = _field(user, "TRANSCRIPT")
    sentences = [s for s in _SENTENCE.split(transcript) if len(s.split()) >= 3] or [transcript]
    cues = {
        "what": r"\b(is|are|means|called|refers to)\b",
        "how": r"\b(by|works?|first|then|step|uses?|using)\b",
        "why": r"\b(because|so that|in order to|reason|helps)\b",
        "impact": r"\b(result|impact|leads? to|which means|ends up|benefit|difference)\b",
    }
    beats: dict[str, BeatCheck] = {}
    for name, pattern in cues.items():
        hit = next((s for s in sentences if re.search(pattern, s, re.I)), None)
        beats[name] = BeatCheck(
            present=hit is not None, evidence=" ".join(hit.split()[:8]) if hit else ""
        )
    present = sum(1 for b in beats.values() if b.present)
    weak = max(sentences, key=lambda s: len(s.split()))
    fixes = {
        "what": "Start by saying plainly what it is.",
        "how": "Next time, walk through how it works step by step.",
        "why": "Try adding why it works that way.",
        "impact": "Finish with the difference it makes in practice.",
    }
    to_fix = next(
        (fixes[n] for n, b in beats.items() if not b.present),
        "Try shortening your longest sentence.",
    )
    return TeachBackScore(
        what=beats["what"],
        how=beats["how"],
        why=beats["why"],
        impact=beats["impact"],
        clarity=min(100, 40 + 15 * present),
        clarity_reason="Scored from how many of the four parts were covered.",
        well_done="You explained it in your own words, which is the hard part.",
        to_fix=to_fix,
        suggestions=[
            "Use shorter sentences.",
            "Signpost with first, then, so.",
            to_fix,
        ],
        weak_sentence=" ".join(weak.split()),
        rewrite=" ".join(weak.split()[:14]).rstrip(",;:") + ".",
    )


class FakeLLM(LLMClient):
    def __init__(self, usage: UsageTracker, delay_s: float = 0.0) -> None:
        self._usage = usage
        self._delay_s = delay_s

    async def complete_structured(
        self,
        kind: ModelKind,
        *,
        system: str,
        user: str,
        schema: type[T],
        session_id: uuid.UUID | None = None,
    ) -> T:
        self._usage.record(
            session_id=session_id, model="fake", input_tokens=0, output_tokens=0, latency_ms=0
        )
        if schema is ExtractedNotes:
            latest = user.split("LATEST:\n", 1)[-1]
            notes = [
                CandidateNote(title=s.strip().rstrip(".!?")[:80], body_md=s.strip())
                for s in _SENTENCE.split(latest)
                if len(s.split()) >= 4
            ]
            return schema.model_validate(ExtractedNotes(notes=notes).model_dump())
        if schema is MergeResult:
            existing = user.split("EXISTING:\n", 1)[1].split("\nNEW:\n", 1)[0].strip()
            new = user.split("\nNEW:\n", 1)[1].strip()
            body = existing if new in existing else f"{existing} {new}"
            return schema.model_validate(MergeResult(body_md=body).model_dump())
        if schema is ReviewDrafts:
            title, body = _field(user, "NOTE TITLE"), _field(user, "NOTE BODY")
            drafts = []
            words = sorted({w for w in re.findall(r"[A-Za-z]{5,}", body)}, key=len, reverse=True)
            if words:
                blank = body.replace(words[0], "_____", 1)
                drafts.append(ReviewDraft(kind="cloze", prompt=blank.strip(), answer=words[0]))
            drafts.append(
                ReviewDraft(
                    kind="question", prompt=f"What do you know about: {title}?", answer=body
                )
            )
            return schema.model_validate(ReviewDrafts(items=drafts).model_dump())
        if schema is QuizTurn:
            expected, given = _field(user, "EXPECTED ANSWER"), _field(user, "ANSWER")
            need = _content_words(expected)
            hit = len(need & _content_words(given)) / len(need) if need else 0.0
            correct = bool(given) and hit >= 0.6
            tier = int(_field(user, "HINT TIER") or 1)
            title, body = _field(user, "NOTE TITLE"), _field(user, "NOTE BODY")
            hint = ""
            if not correct:
                if tier <= 1:
                    hint = f"Think about this idea: {title}. Take another go."
                elif tier == 2:
                    hint = "It starts like this: " + " ".join(expected.split()[:3]) + "."
                else:
                    hint = (
                        f"The answer is {expected}. To put it plainly, {body} "
                        "Can you say that back in your own words?"
                    )
            return schema.model_validate(
                QuizTurn(
                    correct=correct,
                    partial=bool(given) and not correct and hit >= 0.3,
                    missing_points=[] if correct else sorted(need - _content_words(given))[:3],
                    spoken_hint=hint,
                ).model_dump()
            )
        if schema is TrackClassification:
            slugs = re.findall(r"^- ([a-z0-9-]+):", user, re.M)
            return schema.model_validate(
                TrackClassification(
                    track=slugs[0] if slugs else "ai-eng",
                    topic=_field(user, "SOURCE TITLE")[:60] or "general",
                    confidence=0.9,
                ).model_dump()
            )
        if schema is SourceNotes:
            found = []
            for m in re.finditer(r"^\[(\d+)\]\n(.*?)(?=^\[\d+\]\n|\Z)", user, re.S | re.M):
                number, body = int(m.group(1)), m.group(2).strip()
                sentence = next((s for s in _SENTENCE.split(body) if len(s.split()) >= 6), None)
                if sentence:
                    quote = " ".join(sentence.split()[:8])
                    found.append(
                        SourceNote(
                            title=sentence.strip().rstrip(".!?")[:80],
                            body_md=sentence.strip(),
                            citations=[SourceCitation(chunk=number, quote=quote)],
                        )
                    )
            return schema.model_validate(SourceNotes(notes=found).model_dump())
        if schema is TeachBackScore:
            return schema.model_validate(_fake_teach_back(user).model_dump())
        if schema is WalkthroughDraft:
            text = user.lower()
            if not any(
                k in text for k in ("pointer", "binary search", "sliding window", "prefix sum")
            ):
                return schema.model_validate(WalkthroughDraft(applicable=False).model_dump())
            walk_steps = [
                WalkthroughStep(
                    caption="Start with a pointer at each end.",
                    pointers={"left": 0, "right": 5},
                    highlight=[0, 5],
                ),
                WalkthroughStep(
                    caption="The sum is too small, so move left up.",
                    pointers={"left": 1, "right": 5},
                    highlight=[1],
                ),
                WalkthroughStep(
                    caption="Found the pair.", pointers={"left": 1, "right": 4}, highlight=[1, 4]
                ),
            ]
            return schema.model_validate(
                WalkthroughDraft(
                    applicable=True, array=["1", "3", "5", "7", "9", "11"], steps=walk_steps
                ).model_dump()
            )
        if schema is DraftedNotes:
            topic = _field(user, "TOPIC") or "the topic"
            parts = ("what it is", "how it works", "when to use it", "its cost")
            return schema.model_validate(
                DraftedNotes(
                    notes=[
                        CandidateNote(
                            title=f"{topic}: {part}",
                            body_md=f"A starter note on {topic} covering {part}.",
                        )
                        for part in parts
                    ]
                ).model_dump()
            )
        if schema is ReciteExplain:
            note = _field(user, "NOTE") or user
            return schema.model_validate(
                ReciteExplain(
                    text=f"In plain words, {note.split('.')[0].lower()}. "
                    "Think of it like a shortcut you use every day, and it matters because it "
                    "saves you work later."
                ).model_dump()
            )
        if schema is DiscussionSummary:
            problem = _field(user, "PROBLEM") or "the problem"
            return schema.model_validate(
                DiscussionSummary(
                    verdict=(
                        "You covered the core approach well. The biggest gap is failure handling. "
                        "Next, work out how it scales."
                    ),
                    decision="No decision yet"
                    if "NOTES:\n(no notes" in user
                    else "Use the first design",
                    evaluation_md=(
                        f"## Requirements\n- Discussed for {problem}.\n"
                        "## Approach\n- The learner's approach.\n"
                        "## Tradeoffs\n- Simplicity against scale.\n"
                        "## Gaps and risks\n- Failure handling was not covered.\n"
                        "## Next steps\n- Estimate capacity."
                    ),
                ).model_dump()
            )
        if schema is WhyMatters:
            return schema.model_validate(
                WhyMatters(
                    line="This matters because it connects to the rest of what you know."
                ).model_dump()
            )
        if schema is RouteDecision:
            return schema.model_validate(RouteDecision(mode=Mode.capture).model_dump())
        if schema is DiagramDraft and user.startswith("TOPIC:"):
            topic = _field(user, "TOPIC")
            lines = ["flowchart TD", f'    T["{_q(topic)}"]']
            beats = ["What it is", "How it works", "Why it matters", "Its impact"]
            for i, beat in enumerate(beats, 1):
                lines += [f'    B{i}["{beat}"]', f"    {'T' if i == 1 else f'B{i - 1}'} --> B{i}"]
            return schema.model_validate(
                DiagramDraft(mermaid="\n".join(lines), steps=beats).model_dump()
            )
        if schema is DiagramDraft:
            title = user.split("TITLE: ", 1)[1].split("\nBODY:", 1)[0]
            body = user.split("\nBODY:\n", 1)[1].split("\n\nYour previous", 1)[0]
            steps = [s.strip() for s in _SENTENCE.split(body) if s.strip()][:5]
            lines = ["flowchart TD", f'    N0["{_q(title)}"]']
            for i, step in enumerate(steps, 1):
                lines.append(f'    N{i}["{_q(step)}"]')
                lines.append(f"    N{i - 1} --> N{i}")
            return schema.model_validate(
                DiagramDraft(mermaid="\n".join(lines), steps=steps).model_dump()
            )
        if schema is LinkProposals:
            count = len(re.findall(r"^\[\d+\] ", user, re.MULTILINE))
            links = [
                LinkProposal(candidate=i, kind="related", direction="to")
                for i in range(1, count + 1)
            ]
            return schema.model_validate(LinkProposals(links=links).model_dump())
        raise NotImplementedError(f"FakeLLM has no handler for {schema.__name__}")

    async def stream_text(
        self,
        kind: ModelKind,
        *,
        system: str,
        user: str,
        session_id: uuid.UUID | None = None,
        purpose: str = "ack",
    ) -> AsyncIterator[str]:
        self._usage.record(
            session_id=session_id, model="fake", input_tokens=0, output_tokens=0, latency_ms=0
        )
        topic = _field(user, "TOPIC") or user.strip()
        scripts = {
            "ack": ("Got it, noted. ", "Keep going."),
            "explain": (
                f"First, what it is: {topic} is an idea worth knowing. ",
                "Next, how it works: it follows a few simple steps. ",
                "That matters because it changes how you build things. ",
                "In practice, the impact is better results. Ask me anything.",
            ),
            "explain_simple": (
                "Okay, let's take it slowly. ",
                f"Step one, think of {topic} like something from everyday life. ",
                "Does that make sense?",
            ),
            "chitchat": ("Happy to help. ", "Shall we get back to learning?"),
            "discuss": (
                "That's a reasonable start. ",
                "The main risk is the single database. ",
                "My suggestion is to partition the data by user. ",
                "How would you handle a hot partition?",
            ),
            "recite_answer": (
                "Good question. ",
                f"In short, {_field(user, 'QUESTION').rstrip('?').lower()} comes down to "
                "the idea in your note.",
            ),
            "discuss_choose": (
                "Okay, let's do a design discussion. ",
                "What problem would you like to work through?",
            ),
            "discuss_open": (
                f"Okay, let's work through {_field(user, 'PROBLEM') or 'it'}. ",
                "Who will use it, and roughly how much traffic should it handle?",
            ),
        }
        if purpose == "about":
            named = re.findall(r"^- (.+?) \(", system, re.M)
            seen = (
                f" I can see your notebooks: {', '.join(named)}."
                if named
                else (" I don't see any notebooks yet.")
            )
            scripts["about"] = (
                "I'm Aria, your study companion. ",
                "I can capture notes, explain ideas, quiz you, recite your notes "
                "and discuss designs.",
                seen,
            )
        if purpose == "discuss" and "STAGE: open" in user:
            purpose = "discuss_open"
        elif purpose == "discuss" and "STAGE: choose" in user:
            purpose = "discuss_choose"
        for token in scripts.get(purpose, scripts["ack"]):
            await asyncio.sleep(self._delay_s)
            yield token

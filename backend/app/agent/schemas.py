"""Structured LLM outputs for the agent."""

from typing import Literal

from pydantic import BaseModel, Field


class CandidateNote(BaseModel):
    title: str = Field(description="The idea phrased as a claim or a question")
    body_md: str = Field(description="1-5 sentences of Markdown, only what the user said")


class ExtractedNotes(BaseModel):
    notes: list[CandidateNote] = Field(default_factory=list)


class DraftedNotes(BaseModel):
    """Starter notes the assistant writes on a topic when asked ("write the notes")."""

    notes: list[CandidateNote] = Field(default_factory=list)


class MergeResult(BaseModel):
    body_md: str = Field(description="Existing note and the new statement combined, 1-5 sentences")


class DiagramDraft(BaseModel):
    mermaid: str = Field(
        description="Mermaid source: flowchart TD/LR, sequenceDiagram or mindmap. No code fences."
    )
    steps: list[str] = Field(
        default_factory=list,
        description="The same idea as 2-6 short plain steps, used if the diagram cannot render",
    )


class LinkProposal(BaseModel):
    candidate: int = Field(description="Number of the candidate note, as listed")
    kind: Literal["prerequisite", "related", "example_of", "contrasts", "appears_in"]
    direction: Literal["to", "from"] = Field(
        description="'to': the new note points at the candidate; 'from': the candidate points at it"
    )


class LinkProposals(BaseModel):
    links: list[LinkProposal] = Field(default_factory=list)


class ReviewDraft(BaseModel):
    kind: Literal["cloze", "question"]
    prompt: str = Field(description="A cloze with ONE blank written as _____, or a direct question")
    answer: str = Field(description="The expected answer, taken from the note only")


class ReviewDrafts(BaseModel):
    items: list[ReviewDraft] = Field(default_factory=list)


class QuizTurn(BaseModel):
    """One quiz turn: grade the spoken answer and prepare the next hint in a single call."""

    correct: bool = Field(description="Matches the expected answer in meaning (lenient on wording)")
    partial: bool = Field(default=False, description="Right direction but missing key points")
    missing_points: list[str] = Field(default_factory=list)
    spoken_hint: str = Field(
        default="", description="What to say next at the requested hint tier. Empty if correct."
    )


class WhyMatters(BaseModel):
    line: str = Field(description="One short spoken sentence on why this note matters")


class TrackClassification(BaseModel):
    track: str = Field(description="Slug of the best-fitting track, exactly as listed")
    topic: str = Field(description="The specific topic within that track, a few words")
    confidence: float = Field(ge=0, le=1, description="How sure you are the track fits (0 to 1)")


class SourceCitation(BaseModel):
    chunk: int = Field(description="Number of the chunk the idea comes from, as listed")
    quote: str = Field(description="A short VERBATIM quote (5 to 25 words) from that chunk")


class SourceNote(BaseModel):
    title: str = Field(description="The idea phrased as a claim or a question")
    body_md: str = Field(description="1-5 sentences of Markdown, only what the source says")
    citations: list[SourceCitation] = Field(default_factory=list)


class SourceNotes(BaseModel):
    notes: list[SourceNote] = Field(default_factory=list)


class WalkthroughStep(BaseModel):
    caption: str = Field(description="One short sentence saying what happens in this step")
    pointers: dict[str, int] = Field(
        default_factory=dict,
        description='Pointer name to array index, e.g. {"left": 0, "right": 5}',
    )
    highlight: list[int] = Field(default_factory=list, description="Indices to emphasise")
    array: list[str] | None = Field(
        default=None, description="The array after this step, only if its values changed"
    )


class WalkthroughDraft(BaseModel):
    applicable: bool = Field(
        description="False unless the idea is a step-by-step procedure over an array or string"
    )
    array: list[str] = Field(default_factory=list, description="The starting array, as strings")
    steps: list[WalkthroughStep] = Field(default_factory=list)


class BeatCheck(BaseModel):
    present: bool
    evidence: str = Field(
        default="",
        description="A short VERBATIM excerpt of the transcript showing it; empty if absent",
    )


class TeachBackScore(BaseModel):
    """The model's judgement of a spoken explanation (counting is done in code)."""

    what: BeatCheck = Field(description="Says what the thing is")
    how: BeatCheck = Field(description="Says how it works, in steps or mechanism")
    why: BeatCheck = Field(description="Says why it works that way or why it matters")
    impact: BeatCheck = Field(description="Says what difference it makes in practice")
    clarity: int = Field(ge=0, le=100, description="How clear and easy to follow, 0 to 100")
    clarity_reason: str = Field(description="One short sentence behind the clarity score")
    well_done: str = Field(description="ONE thing done well, one gentle sentence")
    to_fix: str = Field(description="ONE thing to fix, one gentle sentence")
    suggestions: list[str] = Field(description="2 or 3 concrete, specific suggestions")
    weak_sentence: str = Field(description="One weak sentence copied EXACTLY from the transcript")
    rewrite: str = Field(
        description="That sentence rewritten more clearly, using only the learner's ideas"
    )


class DiscussionSummary(BaseModel):
    """The wrap-up of a worked discussion: a spoken verdict and a written evaluation."""

    verdict: str = Field(description="Two or three short spoken sentences")
    decision: str = Field(description="The approach the learner chose, or 'No decision yet'")
    evaluation_md: str = Field(description="Markdown with the five headings")


class ReciteExplain(BaseModel):
    text: str = Field(description="Two or three spoken sentences explaining the note")


class Contradiction(BaseModel):
    said: str = Field(description="A short quote copied exactly from what the learner said")
    reference: str = Field(description="What the reference material says instead")


class AccuracyCheck(BaseModel):
    """How a spoken explanation lines up with the learner's own notes or source."""

    covered: list[str] = Field(default_factory=list)
    missed: list[str] = Field(default_factory=list)
    contradicted: list[Contradiction] = Field(default_factory=list)
    verdict: str = ""

"""Structured LLM outputs for the agent."""

from typing import Literal

from pydantic import BaseModel, Field


class CandidateNote(BaseModel):
    title: str = Field(description="The idea phrased as a claim or a question")
    body_md: str = Field(description="1-5 sentences of Markdown, only what the user said")


class ExtractedNotes(BaseModel):
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

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

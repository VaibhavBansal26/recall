import uuid
from typing import Any

from pydantic import BaseModel, Field


class CaptureItem(BaseModel):
    """One note touched by a capture turn (display payload)."""

    event_id: uuid.UUID
    action: str  # "created" | "merged"
    similarity: float | None = None
    note_id: uuid.UUID
    title: str
    body_md: str
    origin: str
    confirmed: bool
    before_title: str | None = None
    before_body_md: str | None = None


class DiagramItem(BaseModel):
    note_id: uuid.UUID
    kind: str  # "mermaid" | "steps"
    source: str


class LinkItem(BaseModel):
    id: uuid.UUID
    from_note_id: uuid.UUID
    to_note_id: uuid.UUID
    from_title: str
    to_title: str
    kind: str
    origin: str
    confirmed: bool


class AgentState(BaseModel):
    session_id: uuid.UUID
    track: str
    mode: str = "capture"
    notebook_id: uuid.UUID | None = None  # file new notes here
    user_text: str = ""
    transcript_window: list[str] = Field(default_factory=list)
    active_note_ids: list[uuid.UUID] = Field(default_factory=list)
    pending_questions: list[str] = Field(default_factory=list)
    confusion_flags: list[str] = Field(default_factory=list)
    # Display payload produced by the node that ran.
    captured: list[CaptureItem] = Field(default_factory=list)
    diagrams: list[DiagramItem] = Field(default_factory=list)
    links: list[LinkItem] = Field(default_factory=list)

    def as_update(self) -> dict[str, Any]:
        return self.model_dump()

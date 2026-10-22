import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import DiagramKind, LinkKind, NoteOrigin, PromptKind, Speaker


class HealthOut(BaseModel):
    status: str
    db: str
    voice_provider: str


class TrackOut(BaseModel):
    slug: str
    name: str
    description: str = ""


class SessionCreate(BaseModel):
    track: str = Field(default="ai-eng", description="Track slug")


class SessionOut(BaseModel):
    id: uuid.UUID
    track: str
    mode: str
    started_at: datetime
    ended_at: datetime | None = None
    summary: str | None = None


class UtteranceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    speaker: Speaker
    text: str
    started_at: datetime
    confidence: float | None = None
    interrupted: bool = False


class SessionDetail(SessionOut):
    utterances: list[UtteranceOut]
    usage: "UsageOut | None" = None


class NoteCreate(BaseModel):
    track: str = "ai-eng"
    # "assistant" saves something the assistant said (e.g. an explanation); it stays unconfirmed.
    origin: Literal["user", "assistant"] = "user"
    title: str = Field(min_length=1)
    body_md: str = Field(min_length=1)


class NotePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    body_md: str | None = Field(default=None, min_length=1)
    confirmed: bool | None = None
    fragile: bool | None = None


class NoteOut(BaseModel):
    id: uuid.UUID
    track: str
    title: str
    body_md: str
    origin: NoteOrigin
    confirmed: bool
    fragile: bool = False
    created_at: datetime
    updated_at: datetime


class UndoOut(BaseModel):
    event_id: uuid.UUID
    action: str
    undone: bool


class UsageOut(BaseModel):
    calls: int
    input_tokens: int
    output_tokens: int
    latency_ms: float


class DiagramOut(BaseModel):
    note_id: uuid.UUID
    kind: DiagramKind
    source: str
    created_at: datetime


class LinkOut(BaseModel):
    id: uuid.UUID
    from_note_id: uuid.UUID
    to_note_id: uuid.UUID
    from_title: str
    to_title: str
    kind: LinkKind
    origin: NoteOrigin
    confirmed: bool


class LinkCreate(BaseModel):
    from_note_id: uuid.UUID
    to_note_id: uuid.UUID
    kind: LinkKind = LinkKind.related


class LinkPatch(BaseModel):
    confirmed: bool


class GraphNode(BaseModel):
    id: uuid.UUID
    title: str
    body_md: str
    track: str
    origin: NoteOrigin
    confirmed: bool
    # Memory strength 0..1 (FSRS retrievability). Null until the note has review history (Phase 3).
    strength: float | None = None
    fragile: bool = False
    has_diagram: bool = False


class GraphOut(BaseModel):
    nodes: list[GraphNode]
    edges: list[LinkOut]


class ReviewItemOut(BaseModel):
    id: uuid.UUID
    note_id: uuid.UUID
    note_title: str
    kind: PromptKind
    prompt: str
    due_at: datetime
    last_reviewed_at: datetime | None = None
    fragile: bool = False
    retrievability: float | None = None


class DueOut(BaseModel):
    total_due: int
    next_due_at: datetime | None = None
    items: list[ReviewItemOut]


class GradeIn(BaseModel):
    grade: Literal["again", "hard", "good", "easy"]
    hint_tier_used: int = Field(default=0, ge=0, le=3)
    latency_ms: int | None = Field(default=None, ge=0)


class GradeOut(BaseModel):
    item: ReviewItemOut
    grade: str
    became_fragile: bool
    cleared_fragile: bool
    next_due_at: datetime

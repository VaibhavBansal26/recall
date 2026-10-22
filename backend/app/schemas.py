import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import DiagramKind, LinkKind, NoteOrigin, Speaker


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
    title: str = Field(min_length=1)
    body_md: str = Field(min_length=1)


class NotePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    body_md: str | None = Field(default=None, min_length=1)
    confirmed: bool | None = None


class NoteOut(BaseModel):
    id: uuid.UUID
    track: str
    title: str
    body_md: str
    origin: NoteOrigin
    confirmed: bool
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

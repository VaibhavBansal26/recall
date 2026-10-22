import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import (
    BriefStatus,
    DiagramKind,
    LinkKind,
    NoteOrigin,
    PromptKind,
    SourceKind,
    SourceStatus,
    Speaker,
)


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


class SourceCreate(BaseModel):
    kind: SourceKind | None = Field(default=None, description="Optional; detected from the link")
    uri: str | None = Field(default=None, max_length=2048)
    text: str | None = Field(default=None, max_length=500_000)
    title: str | None = Field(default=None, max_length=300)
    track_hint: str | None = Field(default=None, description="Track slug; skips classification")


class SourceOut(BaseModel):
    id: uuid.UUID
    kind: SourceKind
    uri: str
    title: str | None = None
    status: SourceStatus
    stage: str | None = None
    error: str | None = None
    track: str | None = None
    track_name: str | None = None
    topic: str | None = None
    suggested_track: str | None = None
    track_confidence: float | None = None
    headline: str | None = None
    created_at: datetime
    updated_at: datetime
    deduplicated: bool = False


class CitationOut(BaseModel):
    chunk_idx: int
    quote: str


class SourceItemOut(BaseModel):
    event_id: uuid.UUID
    action: str
    note_id: uuid.UUID | None = None
    title: str | None = None
    body_md: str | None = None
    before_body_md: str | None = None
    origin: NoteOrigin | None = None
    confirmed: bool = False
    undone: bool = False
    citations: list[CitationOut] = Field(default_factory=list)


class SourceSummaryOut(BaseModel):
    created: int
    merged: int
    linked: int
    chunks: int


class SourceDetail(SourceOut):
    summary: SourceSummaryOut | None = None
    items: list[SourceItemOut] = Field(default_factory=list)


class TrackChoice(BaseModel):
    track: str


class ExportFile(BaseModel):
    path: str
    content: str


class ExportOut(BaseModel):
    files: list[ExportFile]


class BriefQuestion(BaseModel):
    item_id: uuid.UUID
    note_id: uuid.UUID
    note_title: str
    kind: PromptKind
    prompt: str  # never the answer


class BriefOut(BaseModel):
    id: uuid.UUID
    date: date
    status: BriefStatus
    track: str
    due_today: int
    questions: list[BriefQuestion]
    created: bool = True  # False when today's brief already existed
    started_at: datetime | None = None
    completed_at: datetime | None = None


class RetentionPoint(BaseModel):
    date: date
    reviews: int
    recalled: int
    retention: float | None = None


class WeakNodeOut(BaseModel):
    note_id: uuid.UUID
    title: str
    item_id: uuid.UUID
    strength: float | None = None
    fragile: bool = False
    lapses: int = 0


class ArticulationPoint(BaseModel):
    date: date
    clarity: float
    structure: float
    filler_rate: float
    wpm: float


class StatsOut(BaseModel):
    due_now: int
    due_today: int
    next_due_at: datetime | None = None
    items_total: int
    items_reviewed: int
    notes_total: int
    fragile_notes: int
    sources_awaiting: int
    reviews_today: int
    reviewed_today: bool
    streak_current: int
    streak_longest: int
    retention_7d: float | None = None
    retention_30d: float | None = None
    unaided_rate_30d: float | None = None
    average_retrievability: float | None = None
    retention_curve: list[RetentionPoint]
    weak_nodes: list[WeakNodeOut]
    # Filled by the English track's teach-back scoring (Phase 6); empty until then.
    articulation_trend: list[ArticulationPoint] = Field(default_factory=list)

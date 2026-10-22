import enum
import uuid
from datetime import UTC, date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import EMBEDDING_DIM, LOCAL_USER_ID
from app.db.base import Base


def _now() -> datetime:
    return datetime.now(UTC)


class Speaker(enum.StrEnum):
    user = "user"
    assistant = "assistant"


class NoteOrigin(enum.StrEnum):
    user = "user"
    source = "source"
    assistant = "assistant"


class LinkKind(enum.StrEnum):
    prerequisite = "prerequisite"  # from_note must be understood before to_note
    related = "related"
    example_of = "example_of"  # from_note is an example of to_note
    contrasts = "contrasts"
    appears_in = "appears_in"  # from_note appears in to_note


class BriefStatus(enum.StrEnum):
    ready = "ready"  # built (by the morning cron), waiting for the user to press start
    started = "started"
    completed = "completed"
    empty = "empty"  # nothing worth asking about today


class SourceKind(enum.StrEnum):
    url = "url"
    pdf = "pdf"
    youtube = "youtube"
    text = "text"


class SourceStatus(enum.StrEnum):
    queued = "queued"
    fetching = "fetching"
    processing = "processing"
    needs_track = "needs_track"  # classification was not confident; waiting for the user
    ready = "ready"  # notes are filed and waiting for approval
    approved = "approved"
    failed = "failed"


class PromptKind(enum.StrEnum):
    cloze = "cloze"
    question = "question"
    explain = "explain"
    teachback = "teachback"


class DiagramKind(enum.StrEnum):
    mermaid = "mermaid"
    steps = "steps"


class CaptureAction(enum.StrEnum):
    created = "created"
    merged = "merged"


class Track(Base):
    __tablename__ = "tracks"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=sql_text("gen_random_uuid()")
    )
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=sql_text("'{}'::jsonb")
    )


class LearningSession(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=sql_text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(default=LOCAL_USER_ID, index=True)
    track_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tracks.id"))
    mode: Mapped[str] = mapped_column(String(32), default="chitchat", server_default="chitchat")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=sql_text("now()")
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[str | None] = mapped_column(Text)

    track: Mapped[Track] = relationship(lazy="joined")
    utterances: Mapped[list["Utterance"]] = relationship(
        back_populates="session", lazy="selectin", order_by="Utterance.started_at"
    )


class Utterance(Base):
    __tablename__ = "utterances"
    __table_args__ = (Index("ix_utterances_session_started", "session_id", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=sql_text("gen_random_uuid()")
    )
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    speaker: Mapped[Speaker] = mapped_column(Enum(Speaker, name="speaker"))
    text: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=sql_text("now()")
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    # Assistant turn cut off by barge-in; `text` holds what was actually spoken.
    interrupted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    session: Mapped[LearningSession] = relationship(back_populates="utterances")


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (
        Index(
            "ix_notes_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index(
            "ix_notes_fts",
            sql_text("to_tsvector('english', title || ' ' || body_md)"),
            postgresql_using="gin",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=sql_text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(default=LOCAL_USER_ID, index=True)
    track_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tracks.id"), index=True)
    title: Mapped[str] = mapped_column(Text)
    body_md: Mapped[str] = mapped_column(Text)
    origin: Mapped[NoteOrigin] = mapped_column(Enum(NoteOrigin, name="note_origin"))
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Set when the learner struggled with this note (confusion, or repeated reveals in a quiz).
    fragile: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=sql_text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, server_default=sql_text("now()")
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    track: Mapped[Track] = relationship(lazy="joined")


class CaptureEvent(Base):
    """What a capture turn did to a note, so the UI can show it and undo it."""

    __tablename__ = "capture_events"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=sql_text("gen_random_uuid()")
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL")
    )
    note_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("notes.id", ondelete="CASCADE"))
    action: Mapped[CaptureAction] = mapped_column(Enum(CaptureAction, name="capture_action"))
    similarity: Mapped[float | None] = mapped_column(Float)
    # Set when an ingested source caused this change (session_id is then null).
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    # Note state before a merge: {"title", "body_md", "embedding"}. Null for creations.
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    undone: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=sql_text("now()")
    )

    note: Mapped[Note | None] = relationship(lazy="joined")


class NoteLink(Base):
    __tablename__ = "note_links"
    __table_args__ = (UniqueConstraint("from_note_id", "to_note_id", "kind"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=sql_text("gen_random_uuid()")
    )
    from_note_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), index=True
    )
    to_note_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[LinkKind] = mapped_column(Enum(LinkKind, name="link_kind"))
    origin: Mapped[NoteOrigin] = mapped_column(
        Enum(NoteOrigin, name="note_origin", create_type=False)
    )
    # Assistant-proposed links stay unconfirmed (and look different) until the user accepts them.
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=sql_text("now()")
    )

    from_note: Mapped[Note] = relationship(foreign_keys=[from_note_id], lazy="joined")
    to_note: Mapped[Note] = relationship(foreign_keys=[to_note_id], lazy="joined")


class Diagram(Base):
    """The current diagram for a note; regenerating replaces it."""

    __tablename__ = "diagrams"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=sql_text("gen_random_uuid()")
    )
    note_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), unique=True
    )
    kind: Mapped[DiagramKind] = mapped_column(Enum(DiagramKind, name="diagram_kind"))
    source: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=sql_text("now()")
    )


class ReviewItem(Base):
    __tablename__ = "review_items"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=sql_text("gen_random_uuid()")
    )
    note_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), index=True
    )
    prompt_kind: Mapped[PromptKind] = mapped_column(Enum(PromptKind, name="prompt_kind"))
    prompt: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    fsrs_state: Mapped[dict[str, Any]] = mapped_column(JSONB)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fragile: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=sql_text("now()")
    )

    note: Mapped[Note] = relationship(lazy="joined")


class ReviewLog(Base):
    __tablename__ = "review_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=sql_text("gen_random_uuid()")
    )
    review_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("review_items.id", ondelete="CASCADE"), index=True
    )
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    grade: Mapped[int] = mapped_column(SmallInteger)  # FSRS rating: 1 Again .. 4 Easy
    hint_tier_used: Mapped[int] = mapped_column(SmallInteger, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL")
    )


class ConfusionEvent(Base):
    __tablename__ = "confusion_events"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=sql_text("gen_random_uuid()")
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL")
    )
    note_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("notes.id", ondelete="SET NULL"))
    trigger: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=sql_text("now()")
    )


class Source(Base):
    """Material fed in from outside (link, PDF, YouTube, pasted text) that is filed into notes."""

    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("user_id", "uri"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=sql_text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(default=LOCAL_USER_ID, index=True)
    track_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tracks.id"))
    kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind, name="source_kind"))
    # Normalised URL, or "sha256:<hash>" for uploads and pasted text. Unique per user: ingesting
    # the same thing twice does not duplicate it.
    uri: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    status: Mapped[SourceStatus] = mapped_column(
        Enum(SourceStatus, name="source_status"),
        default=SourceStatus.queued,
        server_default="queued",
    )
    stage: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    topic: Mapped[str | None] = mapped_column(Text)
    track_hint: Mapped[str | None] = mapped_column(String(64))
    suggested_track: Mapped[str | None] = mapped_column(String(64))
    track_confidence: Mapped[float | None] = mapped_column(Float)
    raw_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=sql_text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, server_default=sql_text("now()")
    )

    track: Mapped[Track | None] = relationship(lazy="joined")


class SourceChunk(Base):
    __tablename__ = "source_chunks"
    __table_args__ = (
        UniqueConstraint("source_id", "idx"),
        Index(
            "ix_source_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=sql_text("gen_random_uuid()")
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    idx: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))


class NoteCitation(Base):
    """Where in a source a note's content came from: the chunk and a verbatim quote."""

    __tablename__ = "note_citations"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=sql_text("gen_random_uuid()")
    )
    note_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_chunks.id", ondelete="CASCADE"))
    quote: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=sql_text("now()")
    )

    chunk: Mapped[SourceChunk] = relationship(lazy="joined")


class DailyBrief(Base):
    """One spoken morning brief per day: the weakest notes, one question each."""

    __tablename__ = "daily_briefs"
    __table_args__ = (UniqueConstraint("user_id", "brief_date"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=sql_text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(default=LOCAL_USER_ID)
    track_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tracks.id"))
    brief_date: Mapped[date] = mapped_column(Date)  # in the user's time zone
    status: Mapped[BriefStatus] = mapped_column(Enum(BriefStatus, name="brief_status"))
    # Review item ids in the order they will be asked.
    item_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    due_today: Mapped[int] = mapped_column(Integer, default=0)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=sql_text("now()")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    track: Mapped[Track] = relationship(lazy="joined")

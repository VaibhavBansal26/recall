import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
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
    # Plain column for now; FK to `sources` is added with that table in Phase 4.
    source_id: Mapped[uuid.UUID | None] = mapped_column()
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

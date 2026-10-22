"""sources, source_chunks, note_citations; capture_events.source_id; notes.source_id FK

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-23
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID_PK = sa.text("gen_random_uuid()")
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=UUID_PK),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("track_id", sa.Uuid(), sa.ForeignKey("tracks.id")),
        sa.Column(
            "kind", postgresql.ENUM("url", "pdf", "youtube", "text", name="source_kind"), nullable=False
        ),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column(
            "status",
            postgresql.ENUM(
                "queued",
                "fetching",
                "processing",
                "needs_track",
                "ready",
                "approved",
                "failed",
                name="source_status",
            ),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("stage", sa.String(64)),
        sa.Column("error", sa.Text()),
        sa.Column("topic", sa.Text()),
        sa.Column("track_hint", sa.String(64)),
        sa.Column("suggested_track", sa.String(64)),
        sa.Column("track_confidence", sa.Float()),
        sa.Column("raw_text", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("user_id", "uri"),
    )
    op.create_index("ix_sources_user_id", "sources", ["user_id"])

    op.create_table(
        "source_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=UUID_PK),
        sa.Column(
            "source_id", sa.Uuid(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1024)),
        sa.UniqueConstraint("source_id", "idx"),
    )
    op.create_index("ix_source_chunks_source_id", "source_chunks", ["source_id"])
    op.create_index(
        "ix_source_chunks_embedding",
        "source_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "note_citations",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=UUID_PK),
        sa.Column("note_id", sa.Uuid(), sa.ForeignKey("notes.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "source_id", sa.Uuid(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "chunk_id",
            sa.Uuid(),
            sa.ForeignKey("source_chunks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_note_citations_note_id", "note_citations", ["note_id"])
    op.create_index("ix_note_citations_source_id", "note_citations", ["source_id"])

    op.create_foreign_key(
        "fk_notes_source_id", "notes", "sources", ["source_id"], ["id"], ondelete="SET NULL"
    )
    op.add_column(
        "capture_events",
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("sources.id", ondelete="CASCADE")),
    )
    op.create_index("ix_capture_events_source_id", "capture_events", ["source_id"])


def downgrade() -> None:
    op.drop_index("ix_capture_events_source_id", table_name="capture_events")
    op.drop_column("capture_events", "source_id")
    op.drop_constraint("fk_notes_source_id", "notes", type_="foreignkey")
    op.drop_table("note_citations")
    op.drop_table("source_chunks")
    op.drop_table("sources")
    op.execute("DROP TYPE IF EXISTS source_status")
    op.execute("DROP TYPE IF EXISTS source_kind")

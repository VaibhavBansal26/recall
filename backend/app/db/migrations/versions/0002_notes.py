"""notes, capture events, utterances.interrupted

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-22
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID_PK = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.add_column(
        "utterances",
        sa.Column("interrupted", sa.Boolean(), nullable=False, server_default="false"),
    )

    op.create_table(
        "notes",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=UUID_PK),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("track_id", sa.Uuid(), sa.ForeignKey("tracks.id"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column(
            "origin",
            postgresql.ENUM("user", "source", "assistant", name="note_origin"),
            nullable=False,
        ),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("source_id", sa.Uuid()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("embedding", Vector(1024)),
    )
    op.create_index("ix_notes_user_id", "notes", ["user_id"])
    op.create_index("ix_notes_track_id", "notes", ["track_id"])
    op.create_index(
        "ix_notes_embedding",
        "notes",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_notes_fts",
        "notes",
        [sa.text("to_tsvector('english', title || ' ' || body_md)")],
        postgresql_using="gin",
    )

    op.create_table(
        "capture_events",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=UUID_PK),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="SET NULL")),
        sa.Column("note_id", sa.Uuid(), sa.ForeignKey("notes.id", ondelete="CASCADE")),
        sa.Column(
            "action", postgresql.ENUM("created", "merged", name="capture_action"), nullable=False
        ),
        sa.Column("similarity", sa.Float()),
        sa.Column("before", postgresql.JSONB()),
        sa.Column("undone", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )


def downgrade() -> None:
    op.drop_table("capture_events")
    op.execute("DROP TYPE IF EXISTS capture_action")
    op.drop_table("notes")
    op.execute("DROP TYPE IF EXISTS note_origin")
    op.drop_column("utterances", "interrupted")

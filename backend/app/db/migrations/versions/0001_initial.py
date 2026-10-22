"""initial: tracks, sessions, utterances

Revision ID: 0001
Revises:
Create Date: 2026-10-22
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID_PK = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "tracks",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=UUID_PK),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=UUID_PK),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("track_id", sa.Uuid(), sa.ForeignKey("tracks.id"), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False, server_default="chitchat"),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("summary", sa.Text()),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.create_table(
        "utterances",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=UUID_PK),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("speaker", postgresql.ENUM("user", "assistant", name="speaker"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("confidence", sa.Float()),
    )
    op.create_index(
        "ix_utterances_session_started", "utterances", ["session_id", "started_at"]
    )


def downgrade() -> None:
    op.drop_table("utterances")
    op.execute("DROP TYPE IF EXISTS speaker")
    op.drop_table("sessions")
    op.drop_table("tracks")

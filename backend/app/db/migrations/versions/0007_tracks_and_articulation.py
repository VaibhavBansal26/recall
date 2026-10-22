"""articulation_scores, utterances.words, diagram_kind 'walkthrough'

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-23
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("utterances", sa.Column("words", postgresql.JSONB()))
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE diagram_kind ADD VALUE IF NOT EXISTS 'walkthrough'")
    op.create_table(
        "articulation_scores",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="SET NULL")),
        sa.Column("note_id", sa.Uuid(), sa.ForeignKey("notes.id", ondelete="SET NULL")),
        sa.Column("clarity", sa.Float(), nullable=False),
        sa.Column("structure", sa.Float(), nullable=False),
        sa.Column("filler_rate", sa.Float(), nullable=False),
        sa.Column("wpm", sa.Float()),
        sa.Column("feedback", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index("ix_articulation_scores_created_at", "articulation_scores", ["created_at"])


def downgrade() -> None:
    op.drop_table("articulation_scores")
    op.drop_column("utterances", "words")
    # Postgres cannot drop an enum value; 'walkthrough' stays in the type.

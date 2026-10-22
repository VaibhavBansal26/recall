"""review items, review logs, confusion events, notes.fragile

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-22
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID_PK = sa.text("gen_random_uuid()")
NOW = sa.text("now()")


def upgrade() -> None:
    op.add_column("notes", sa.Column("fragile", sa.Boolean(), nullable=False, server_default="false"))

    op.create_table(
        "review_items",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=UUID_PK),
        sa.Column("note_id", sa.Uuid(), sa.ForeignKey("notes.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "prompt_kind",
            postgresql.ENUM("cloze", "question", "explain", "teachback", name="prompt_kind"),
            nullable=False,
        ),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("fsrs_state", postgresql.JSONB(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("fragile", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_review_items_note_id", "review_items", ["note_id"])
    op.create_index("ix_review_items_due_at", "review_items", ["due_at"])

    op.create_table(
        "review_logs",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=UUID_PK),
        sa.Column(
            "review_item_id",
            sa.Uuid(),
            sa.ForeignKey("review_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("grade", sa.SmallInteger(), nullable=False),
        sa.Column("hint_tier_used", sa.SmallInteger(), nullable=False),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="SET NULL")),
    )
    op.create_index("ix_review_logs_review_item_id", "review_logs", ["review_item_id"])

    op.create_table(
        "confusion_events",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=UUID_PK),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="SET NULL")),
        sa.Column("note_id", sa.Uuid(), sa.ForeignKey("notes.id", ondelete="SET NULL")),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )


def downgrade() -> None:
    op.drop_table("confusion_events")
    op.drop_table("review_logs")
    op.drop_table("review_items")
    op.execute("DROP TYPE IF EXISTS prompt_kind")
    op.drop_column("notes", "fragile")

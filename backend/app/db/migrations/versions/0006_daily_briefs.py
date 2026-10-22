"""daily briefs

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-23
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_briefs",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("track_id", sa.Uuid(), sa.ForeignKey("tracks.id"), nullable=False),
        sa.Column("brief_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM("ready", "started", "completed", "empty", name="brief_status"),
            nullable=False,
        ),
        sa.Column("item_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("due_today", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("sessions.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "brief_date"),
    )


def downgrade() -> None:
    op.drop_table("daily_briefs")
    op.execute("DROP TYPE IF EXISTS brief_status")

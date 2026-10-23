"""notebooks (named files of notes inside a track) and notes.notebook_id

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-23
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notebooks",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("track_id", sa.Uuid(), sa.ForeignKey("tracks.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("notes", "discussion", "source", name="notebook_kind"),
            nullable=False,
            server_default="notes",
        ),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("sources.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("track_id", "slug"),
    )
    op.create_index("ix_notebooks_user_id", "notebooks", ["user_id"])
    op.create_index("ix_notebooks_track_id", "notebooks", ["track_id"])
    op.add_column(
        "notes",
        sa.Column("notebook_id", sa.Uuid(), sa.ForeignKey("notebooks.id", ondelete="SET NULL")),
    )
    op.create_index("ix_notes_notebook_id", "notes", ["notebook_id"])


def downgrade() -> None:
    op.drop_index("ix_notes_notebook_id", table_name="notes")
    op.drop_column("notes", "notebook_id")
    op.drop_table("notebooks")
    op.execute("DROP TYPE notebook_kind")

"""note_links and diagrams

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-22
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID_PK = sa.text("gen_random_uuid()")


def upgrade() -> None:
    op.create_table(
        "note_links",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=UUID_PK),
        sa.Column(
            "from_note_id", sa.Uuid(), sa.ForeignKey("notes.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "to_note_id", sa.Uuid(), sa.ForeignKey("notes.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "kind",
            postgresql.ENUM(
                "prerequisite", "related", "example_of", "contrasts", "appears_in", name="link_kind"
            ),
            nullable=False,
        ),
        sa.Column(
            "origin",
            postgresql.ENUM("user", "source", "assistant", name="note_origin", create_type=False),
            nullable=False,
        ),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("from_note_id", "to_note_id", "kind"),
    )
    op.create_index("ix_note_links_from_note_id", "note_links", ["from_note_id"])
    op.create_index("ix_note_links_to_note_id", "note_links", ["to_note_id"])

    op.create_table(
        "diagrams",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=UUID_PK),
        sa.Column(
            "note_id",
            sa.Uuid(),
            sa.ForeignKey("notes.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "kind", postgresql.ENUM("mermaid", "steps", name="diagram_kind"), nullable=False
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )


def downgrade() -> None:
    op.drop_table("diagrams")
    op.execute("DROP TYPE IF EXISTS diagram_kind")
    op.drop_table("note_links")
    op.execute("DROP TYPE IF EXISTS link_kind")

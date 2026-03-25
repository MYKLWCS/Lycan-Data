"""Add family_tree_snapshots table

Revision ID: c4d5e6f7a8b9
Revises: d4e5f6a7b8c9
Create Date: 2026-03-25

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TS_COLS = [
    sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    ),
]


def upgrade() -> None:
    op.create_table(
        "family_tree_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("root_person_id", sa.UUID(), nullable=False),
        sa.Column(
            "tree_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("depth_ancestors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("depth_descendants", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_stale", sa.Boolean(), nullable=False, server_default="false"),
        *_TS_COLS,
        sa.ForeignKeyConstraint(["root_person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_family_tree_snapshots_root_person_id",
        "family_tree_snapshots",
        ["root_person_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_family_tree_snapshots_root_person_id", table_name="family_tree_snapshots")
    op.drop_table("family_tree_snapshots")

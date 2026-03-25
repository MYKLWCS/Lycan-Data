"""Add system_audits table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-25

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_audits",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        # Per-person quality metrics
        sa.Column("persons_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("persons_low_coverage", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("persons_stale", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("persons_conflict", sa.Integer(), nullable=False, server_default="0"),
        # Crawler health
        sa.Column("crawlers_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("crawlers_healthy", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "crawlers_degraded",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        # Data volume today
        sa.Column("tags_assigned_today", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("merges_today", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("persons_ingested_today", sa.Integer(), nullable=False, server_default="0"),
        # Freeform metadata
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        # TimestampMixin columns
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_system_audits_run_at", "system_audits", ["run_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_system_audits_run_at", table_name="system_audits")
    op.drop_table("system_audits")

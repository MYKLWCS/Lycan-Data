"""Add persons.merged_into and dedup_reviews table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-25

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── persons.merged_into ──────────────────────────────────────────────────
    op.add_column(
        "persons",
        sa.Column("merged_into", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_persons_merged_into", "persons", ["merged_into"], unique=False
    )
    op.create_foreign_key(
        "fk_persons_merged_into_persons",
        "persons",
        "persons",
        ["merged_into"],
        ["id"],
        ondelete="SET NULL",
    )

    # ── dedup_reviews ────────────────────────────────────────────────────────
    op.create_table(
        "dedup_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_a_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_b_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("similarity_score", sa.Float(), nullable=False),
        sa.Column("reviewed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("decision", sa.String(length=20), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["person_a_id"], ["persons.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["person_b_id"], ["persons.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dedup_reviews_person_a_id", "dedup_reviews", ["person_a_id"]
    )
    op.create_index(
        "ix_dedup_reviews_person_b_id", "dedup_reviews", ["person_b_id"]
    )
    op.create_index(
        "ix_dedup_reviews_reviewed", "dedup_reviews", ["reviewed"]
    )


def downgrade() -> None:
    op.drop_table("dedup_reviews")
    op.drop_constraint("fk_persons_merged_into_persons", "persons", type_="foreignkey")
    op.drop_index("ix_persons_merged_into", table_name="persons")
    op.drop_column("persons", "merged_into")

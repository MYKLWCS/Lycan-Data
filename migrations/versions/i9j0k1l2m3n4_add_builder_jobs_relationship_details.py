"""Add builder_jobs, builder_job_persons, relationship_details tables.

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-03-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers
revision = "i9j0k1l2m3n4"
down_revision = "h8i9j0k1l2m3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "builder_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("criteria", JSONB, nullable=False, server_default="{}"),
        sa.Column("discovered_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("built_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("filtered_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("expanded_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("relationships_mapped", sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("max_results", sa.Integer, nullable=False, server_default="100"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_builder_jobs_status", "builder_jobs", ["status"])

    op.create_table(
        "builder_job_persons",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", UUID(as_uuid=True), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False, server_default="discovered"),
        sa.Column("enrichment_score", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("match_score", sa.Float, nullable=False, server_default="0.0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_builder_job_persons_job_id", "builder_job_persons", ["job_id"])
    op.create_index("ix_builder_job_persons_person_id", "builder_job_persons", ["person_id"])

    op.create_table(
        "relationship_details",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "relationship_id",
            UUID(as_uuid=True),
            sa.ForeignKey("relationships.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("detailed_type", sa.String(50), nullable=False),
        sa.Column("strength", sa.Integer, nullable=False, server_default="50"),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.5"),
        sa.Column("freshness_score", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("composite_score", sa.Float, nullable=False, server_default="50.0"),
        sa.Column("discovered_via", sa.String(100), nullable=True),
        sa.Column("discovery_sources", JSONB, nullable=False, server_default="[]"),
        sa.Column("source_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "verification_level",
            sa.String(30),
            nullable=False,
            server_default="unverified",
        ),
        sa.Column("relationship_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("relationship_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("conflict", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_relationship_details_relationship_id",
        "relationship_details",
        ["relationship_id"],
    )


def downgrade() -> None:
    op.drop_table("relationship_details")
    op.drop_table("builder_job_persons")
    op.drop_table("builder_jobs")

"""Add criminal_records, identity_documents, credit_profiles, identifier_history tables

Revision ID: a1b2c3d4e5f6
Revises: 0c06f6f7f3f8
Create Date: 2026-03-24

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "0c06f6f7f3f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# DataQualityMixin columns (repeated on each new table)
_DQ_COLS = [
    sa.Column("source_reliability", sa.Float(), nullable=False, server_default="0.5"),
    sa.Column("freshness_score", sa.Float(), nullable=False, server_default="1.0"),
    sa.Column("corroboration_count", sa.Integer(), nullable=False, server_default="1"),
    sa.Column("corroboration_score", sa.Float(), nullable=False, server_default="0.5"),
    sa.Column("conflict_flag", sa.Boolean(), nullable=False, server_default="false"),
    sa.Column("verification_status", sa.String(), nullable=False, server_default="unverified"),
    sa.Column("composite_quality", sa.Float(), nullable=False, server_default="0.5"),
    sa.Column(
        "data_quality", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"
    ),
    sa.Column("last_scraped_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("scraped_from", sa.String(), nullable=True),
]

_TS_COLS = [
    sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    ),
]


def upgrade() -> None:
    # ── criminal_records ─────────────────────────────────────────────────────
    op.create_table(
        "criminal_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("person_id", sa.UUID(), nullable=False),
        sa.Column("record_type", sa.String(length=50), nullable=False, server_default="charge"),
        sa.Column("offense_level", sa.String(length=30), nullable=True),
        sa.Column("charge", sa.String(length=500), nullable=True),
        sa.Column("offense_description", sa.Text(), nullable=True),
        sa.Column("statute", sa.String(length=200), nullable=True),
        sa.Column("court_case_number", sa.String(length=200), nullable=True),
        sa.Column("court_name", sa.String(length=300), nullable=True),
        sa.Column("jurisdiction", sa.String(length=200), nullable=True),
        sa.Column("arrest_date", sa.Date(), nullable=True),
        sa.Column("charge_date", sa.Date(), nullable=True),
        sa.Column("disposition_date", sa.Date(), nullable=True),
        sa.Column("warrant_date", sa.Date(), nullable=True),
        sa.Column("disposition", sa.String(length=100), nullable=True),
        sa.Column("sentence", sa.Text(), nullable=True),
        sa.Column("sentence_months", sa.Integer(), nullable=True),
        sa.Column("probation_months", sa.Integer(), nullable=True),
        sa.Column("fine_usd", sa.Float(), nullable=True),
        sa.Column("has_mugshot", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("mugshot_url_hashed", sa.String(length=64), nullable=True),
        sa.Column("is_sex_offender", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("source_platform", sa.String(length=100), nullable=True),
        sa.Column("source_url_hashed", sa.String(length=64), nullable=True),
        sa.Column(
            "meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"
        ),
        *_DQ_COLS,
        *_TS_COLS,
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_criminal_person_id", "criminal_records", ["person_id"])
    op.create_index("ix_criminal_case_number", "criminal_records", ["court_case_number"])

    # ── identity_documents ───────────────────────────────────────────────────
    op.create_table(
        "identity_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("person_id", sa.UUID(), nullable=False),
        sa.Column("doc_type", sa.String(length=50), nullable=False),
        sa.Column("doc_number_partial", sa.String(length=50), nullable=True),
        sa.Column("issuing_country", sa.String(length=10), nullable=True),
        sa.Column("issuing_state", sa.String(length=100), nullable=True),
        sa.Column("issuing_authority", sa.String(length=200), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("is_expired", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("source_platform", sa.String(length=100), nullable=True),
        sa.Column(
            "meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"
        ),
        *_DQ_COLS,
        *_TS_COLS,
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_idoc_person_id", "identity_documents", ["person_id"])

    # ── credit_profiles ──────────────────────────────────────────────────────
    op.create_table(
        "credit_profiles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("person_id", sa.UUID(), nullable=False),
        sa.Column("estimated_credit_tier", sa.String(length=30), nullable=True),
        sa.Column("estimated_score_min", sa.Integer(), nullable=True),
        sa.Column("estimated_score_max", sa.Integer(), nullable=True),
        sa.Column("bankruptcy_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lien_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("judgment_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("foreclosure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("eviction_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("has_bankruptcy", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("has_tax_lien", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("has_civil_judgment", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("has_foreclosure", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("model_version", sa.String(length=30), nullable=False, server_default="v1"),
        sa.Column("source_platform", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"
        ),
        *_DQ_COLS,
        *_TS_COLS,
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_credit_person_id", "credit_profiles", ["person_id"])

    # ── identifier_history ───────────────────────────────────────────────────
    op.create_table(
        "identifier_history",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("person_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("value", sa.String(length=1024), nullable=False),
        sa.Column("normalized_value", sa.String(length=1024), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column("source_platform", sa.String(length=100), nullable=True),
        sa.Column(
            "meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"
        ),
        *_TS_COLS,
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("person_id", "type", "value", name="uq_idhistory_person_type_value"),
    )
    op.create_index("ix_idhistory_person_id", "identifier_history", ["person_id"])
    op.create_index("ix_idhistory_value", "identifier_history", ["value"])
    op.create_index("ix_idhistory_type", "identifier_history", ["type"])


def downgrade() -> None:
    op.drop_table("identifier_history")
    op.drop_index("ix_credit_person_id", table_name="credit_profiles")
    op.drop_table("credit_profiles")
    op.drop_index("ix_idoc_person_id", table_name="identity_documents")
    op.drop_table("identity_documents")
    op.drop_index("ix_criminal_case_number", table_name="criminal_records")
    op.drop_index("ix_criminal_person_id", table_name="criminal_records")
    op.drop_table("criminal_records")

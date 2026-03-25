"""Add alt_credit_score, aml_risk, marketing_tags_list to persons.

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e1
Create Date: 2026-03-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "g7h8i9j0k1l2"
down_revision: str | Sequence[str] | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("persons", sa.Column("alt_credit_score", sa.Integer(), nullable=True))
    op.add_column("persons", sa.Column("alt_credit_tier", sa.String(20), nullable=True))
    op.add_column("persons", sa.Column("aml_risk_score", sa.Float(), nullable=True))
    op.add_column("persons", sa.Column("aml_risk_tier", sa.String(20), nullable=True))
    op.add_column(
        "persons",
        sa.Column(
            "marketing_tags_list",
            JSONB(),
            server_default="[]",
            nullable=False,
        ),
    )
    op.create_index("ix_persons_alt_credit_score", "persons", ["alt_credit_score"])
    op.create_index("ix_persons_aml_risk_score", "persons", ["aml_risk_score"])


def downgrade() -> None:
    op.drop_index("ix_persons_aml_risk_score", table_name="persons")
    op.drop_index("ix_persons_alt_credit_score", table_name="persons")
    op.drop_column("persons", "marketing_tags_list")
    op.drop_column("persons", "aml_risk_tier")
    op.drop_column("persons", "aml_risk_score")
    op.drop_column("persons", "alt_credit_tier")
    op.drop_column("persons", "alt_credit_score")

"""Add enrichment_score and is_pep columns to persons.

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-03-25 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "h8i9j0k1l2m3"
down_revision: str | Sequence[str] | None = "g7h8i9j0k1l2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("persons", sa.Column("enrichment_score", sa.Float(), nullable=True, server_default="0.0"))
    op.add_column("persons", sa.Column("is_pep", sa.Boolean(), nullable=True, server_default="false"))


def downgrade() -> None:
    op.drop_column("persons", "is_pep")
    op.drop_column("persons", "enrichment_score")

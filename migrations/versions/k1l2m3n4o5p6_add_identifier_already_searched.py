"""add_identifier_already_searched

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-03-29 00:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "k1l2m3n4o5p6"
down_revision: Union[str, Sequence[str], None] = "j0k1l2m3n4o5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "identifiers",
        sa.Column("already_searched", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("identifiers", "already_searched")

"""normalize_identifier_constraint

Revision ID: 0862064daa56
Revises: b2c3d4e5f6a7
Create Date: 2026-03-25 00:28:26.135742

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0862064daa56"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Backfill normalized_value for any rows where it is still NULL
    op.execute(
        "UPDATE identifiers SET normalized_value = lower(trim(value)) WHERE normalized_value IS NULL"
    )

    # 2. Make normalized_value NOT NULL
    op.alter_column(
        "identifiers",
        "normalized_value",
        existing_type=sa.VARCHAR(length=1024),
        nullable=False,
    )

    # 3. Drop the old unique constraint on (type, value)
    op.drop_constraint("uq_identifier_type_value", "identifiers", type_="unique")

    # 4. Create the new unique constraint on (type, normalized_value)
    op.create_unique_constraint(
        "uq_identifier_type_normalized", "identifiers", ["type", "normalized_value"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_identifier_type_normalized", "identifiers", type_="unique")

    op.create_unique_constraint("uq_identifier_type_value", "identifiers", ["type", "value"])

    op.alter_column(
        "identifiers",
        "normalized_value",
        existing_type=sa.VARCHAR(length=1024),
        nullable=True,
    )

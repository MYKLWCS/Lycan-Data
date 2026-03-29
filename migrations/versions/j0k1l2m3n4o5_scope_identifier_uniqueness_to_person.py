"""scope_identifier_uniqueness_to_person

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-03-29 00:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "j0k1l2m3n4o5"
down_revision: Union[str, Sequence[str], None] = "i9j0k1l2m3n4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the old global uniqueness constraint on (type, normalized_value)
    op.drop_constraint("uq_identifier_type_normalized", "identifiers", type_="unique")

    # Create the new person-scoped uniqueness constraint on (person_id, type, normalized_value)
    op.create_unique_constraint(
        "uq_identifier_person_type_value",
        "identifiers",
        ["person_id", "type", "normalized_value"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_identifier_person_type_value", "identifiers", type_="unique")

    op.create_unique_constraint(
        "uq_identifier_type_normalized",
        "identifiers",
        ["type", "normalized_value"],
    )

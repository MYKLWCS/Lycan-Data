"""merge_identifier_and_dedup_branches

Revision ID: 167f63d52b3b
Revises: 0862064daa56, c4d5e6f7a8b9
Create Date: 2026-03-25 13:17:54.048621

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '167f63d52b3b'
down_revision: Union[str, Sequence[str], None] = ('0862064daa56', 'c4d5e6f7a8b9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

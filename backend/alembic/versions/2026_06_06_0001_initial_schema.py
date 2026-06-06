"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-06 00:00:00.000000
"""
from typing import Sequence, Union

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass


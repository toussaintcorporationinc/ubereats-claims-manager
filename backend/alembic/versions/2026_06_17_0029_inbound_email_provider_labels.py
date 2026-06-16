"""Store provider labels on inbound email messages.

Revision ID: 0029_gmail_labels
Revises: 0028_import_row_link_indexes
Create Date: 2026-06-17 00:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_gmail_labels"
down_revision: str | Sequence[str] | None = "0028_import_row_link_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("inbound_email_messages", sa.Column("provider_labels_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("inbound_email_messages", "provider_labels_json")

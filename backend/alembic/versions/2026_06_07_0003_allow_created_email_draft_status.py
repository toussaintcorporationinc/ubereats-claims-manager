"""allow created email draft status

Revision ID: 0003_email_draft_status
Revises: 0002_allow_missing_order_amount
Create Date: 2026-06-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003_email_draft_status"
down_revision: Union[str, None] = "0002_allow_missing_order_amount"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("email_drafts", recreate="always") as batch_op:
            batch_op.drop_constraint("ck_email_drafts_status", type_="check")
            batch_op.create_check_constraint(
                "ck_email_drafts_status",
                "status IN ('created', 'draft', 'ready', 'archived')",
            )
        return

    op.drop_constraint("ck_email_drafts_status", "email_drafts", type_="check")
    op.create_check_constraint(
        "ck_email_drafts_status",
        "email_drafts",
        "status IN ('created', 'draft', 'ready', 'archived')",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("email_drafts", recreate="always") as batch_op:
            batch_op.drop_constraint("ck_email_drafts_status", type_="check")
            batch_op.create_check_constraint(
                "ck_email_drafts_status",
                "status IN ('draft', 'ready', 'archived')",
            )
        return

    op.drop_constraint("ck_email_drafts_status", "email_drafts", type_="check")
    op.create_check_constraint(
        "ck_email_drafts_status",
        "email_drafts",
        "status IN ('draft', 'ready', 'archived')",
    )

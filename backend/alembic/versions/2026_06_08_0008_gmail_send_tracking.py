"""gmail send tracking

Revision ID: 0008_gmail_send_tracking
Revises: 0007_gmail_email_provider
Create Date: 2026-06-08 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_gmail_send_tracking"
down_revision: Union[str, None] = "0007_gmail_email_provider"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_STATUS_CHECK = "status IN ('provider_draft_created', 'send_requested', 'sent', 'failed')"
OLD_STATUS_CHECK = "status IN ('provider_draft_created', 'failed')"


def upgrade() -> None:
    with op.batch_alter_table("email_provider_drafts", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_email_provider_drafts_status", type_="check")
        batch_op.add_column(sa.Column("provider_message_id", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("sent_by_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("last_error", sa.Text(), nullable=True))
        batch_op.create_check_constraint("ck_email_provider_drafts_status", NEW_STATUS_CHECK)


def downgrade() -> None:
    op.execute("UPDATE email_provider_drafts SET status = 'failed' WHERE status NOT IN ('provider_draft_created', 'failed')")
    with op.batch_alter_table("email_provider_drafts", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_email_provider_drafts_status", type_="check")
        batch_op.drop_column("last_error")
        batch_op.drop_column("sent_at")
        batch_op.drop_column("sent_by_user_id")
        batch_op.drop_column("provider_message_id")
        batch_op.create_check_constraint("ck_email_provider_drafts_status", OLD_STATUS_CHECK)

"""add resend email provider

Revision ID: 0023_resend_provider
Revises: 0022_smart_import_routing
Create Date: 2026-06-10 18:30:00.000000
"""

from collections.abc import Sequence
from alembic import op

revision: str = "0023_resend_provider"
down_revision: str | None = "0022_smart_import_routing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMAIL_PROVIDERS = ("internal", "gmail", "resend", "microsoft_graph")
OLD_EMAIL_PROVIDERS = ("internal", "gmail", "microsoft_graph")
EMAIL_PROVIDER_DRAFT_PROVIDERS = ("gmail", "resend")
OLD_EMAIL_PROVIDER_DRAFT_PROVIDERS = ("gmail",)


def check_in_constraint(column_name: str, allowed_values: tuple[str, ...]) -> str:
    quoted_values = ", ".join(f"'{value}'" for value in allowed_values)
    return f"{column_name} IN ({quoted_values})"


def upgrade() -> None:
    with op.batch_alter_table("email_threads") as batch_op:
        batch_op.drop_constraint("ck_email_threads_provider", type_="check")
        batch_op.create_check_constraint("ck_email_threads_provider", check_in_constraint("provider", EMAIL_PROVIDERS))

    with op.batch_alter_table("email_provider_drafts") as batch_op:
        batch_op.drop_constraint("ck_email_provider_drafts_provider", type_="check")
        batch_op.create_check_constraint(
            "ck_email_provider_drafts_provider",
            check_in_constraint("provider", EMAIL_PROVIDER_DRAFT_PROVIDERS),
        )


def downgrade() -> None:
    with op.batch_alter_table("email_provider_drafts") as batch_op:
        batch_op.drop_constraint("ck_email_provider_drafts_provider", type_="check")
        batch_op.create_check_constraint(
            "ck_email_provider_drafts_provider",
            check_in_constraint("provider", OLD_EMAIL_PROVIDER_DRAFT_PROVIDERS),
        )

    with op.batch_alter_table("email_threads") as batch_op:
        batch_op.drop_constraint("ck_email_threads_provider", type_="check")
        batch_op.create_check_constraint(
            "ck_email_threads_provider",
            check_in_constraint("provider", OLD_EMAIL_PROVIDERS),
        )

"""auth roles

Revision ID: 0004_auth_roles
Revises: 0003_email_draft_status
Create Date: 2026-06-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_auth_roles"
down_revision: Union[str, None] = "0003_email_draft_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=500), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'manager', 'staff')", name="ck_users_role"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "user_restaurant_access",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "restaurant_id", name="uq_user_restaurant_access"),
    )
    op.create_index("ix_user_restaurant_access_restaurant_id", "user_restaurant_access", ["restaurant_id"])
    op.create_index("ix_user_restaurant_access_user_id", "user_restaurant_access", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_restaurant_access_user_id", table_name="user_restaurant_access")
    op.drop_index("ix_user_restaurant_access_restaurant_id", table_name="user_restaurant_access")
    op.drop_table("user_restaurant_access")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

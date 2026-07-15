"""Canonicalize Asian Passion and requeue its unresolved starred Gmail threads.

Revision ID: 0031_asian_passion_identity
Revises: 0030_gmail_watched_threads
Create Date: 2026-07-15 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision: str = "0031_asian_passion_identity"
down_revision: str | Sequence[str] | None = "0030_gmail_watched_threads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc)

    restaurants = sa.table(
        "restaurants",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    claim_orders = sa.table(
        "claim_orders",
        sa.column("id", sa.Integer),
        sa.column("restaurant_id", sa.Integer),
    )
    inbound_messages = sa.table(
        "inbound_email_messages",
        sa.column("id", sa.Integer),
        sa.column("order_id", sa.Integer),
        sa.column("received_at", sa.DateTime(timezone=True)),
        sa.column("review_status", sa.String),
        sa.column("reviewed_at", sa.DateTime(timezone=True)),
        sa.column("reviewed_by_user_id", sa.Integer),
    )
    watched_threads = sa.table(
        "gmail_watched_threads",
        sa.column("id", sa.Integer),
        sa.column("claim_order_id", sa.Integer),
        sa.column("status", sa.String),
        sa.column("star_active", sa.Boolean),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    work_items = sa.table(
        "gmail_starred_work_items",
        sa.column("id", sa.Integer),
        sa.column("watched_thread_id", sa.Integer),
        sa.column("inbound_message_id", sa.Integer),
        sa.column("status", sa.String),
        sa.column("reason", sa.String),
        sa.column("processed_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    email_drafts = sa.table(
        "email_drafts",
        sa.column("id", sa.Integer),
        sa.column("order_id", sa.Integer),
        sa.column("subject", sa.String),
        sa.column("body", sa.Text),
    )
    appeal_attempts = sa.table(
        "appeal_attempts",
        sa.column("id", sa.Integer),
        sa.column("based_on_refusal_message_id", sa.Integer),
        sa.column("email_draft_id", sa.Integer),
        sa.column("provider_draft_id", sa.Integer),
    )
    provider_drafts = sa.table(
        "email_provider_drafts",
        sa.column("id", sa.Integer),
        sa.column("status", sa.String),
        sa.column("last_error", sa.Text),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    restaurant_rows = bind.execute(sa.select(restaurants.c.id, restaurants.c.name)).all()
    old_restaurant_ids = [
        row.id for row in restaurant_rows if normalized_name(row.name) == "crousty best"
    ]
    asian_passion_ids = [
        row.id
        for row in restaurant_rows
        if normalized_name(row.name) in {"asian passion", "asian passion ex crousty best"}
    ]
    if len(old_restaurant_ids) == 1 and not asian_passion_ids:
        bind.execute(
            restaurants.update()
            .where(restaurants.c.id == old_restaurant_ids[0])
            .values(name="Asian Passion", updated_at=now)
        )

    target_restaurant_ids = sorted({*old_restaurant_ids, *asian_passion_ids})
    if not target_restaurant_ids:
        return

    stale_provider_draft_ids = list(
        bind.execute(
            sa.select(provider_drafts.c.id)
            .select_from(
                provider_drafts.join(
                    appeal_attempts,
                    appeal_attempts.c.provider_draft_id == provider_drafts.c.id,
                )
                .join(email_drafts, email_drafts.c.id == appeal_attempts.c.email_draft_id)
                .join(claim_orders, claim_orders.c.id == email_drafts.c.order_id)
            )
            .where(
                claim_orders.c.restaurant_id.in_(target_restaurant_ids),
                provider_drafts.c.status == "provider_draft_created",
                sa.or_(
                    sa.func.lower(sa.func.coalesce(email_drafts.c.subject, "")).like("%crousty best%"),
                    sa.func.lower(sa.func.coalesce(email_drafts.c.body, "")).like("%crousty best%"),
                ),
            )
        ).scalars()
    )
    if stale_provider_draft_ids:
        bind.execute(
            provider_drafts.update()
            .where(provider_drafts.c.id.in_(stale_provider_draft_ids))
            .values(
                status="failed",
                last_error="superseded_restaurant_identity",
                updated_at=now,
            )
        )

    candidate_rows = bind.execute(
        sa.select(
            work_items.c.id.label("work_item_id"),
            watched_threads.c.id.label("watched_thread_id"),
            inbound_messages.c.id.label("inbound_message_id"),
            inbound_messages.c.received_at,
        )
        .select_from(
            work_items.join(
                watched_threads,
                watched_threads.c.id == work_items.c.watched_thread_id,
            )
            .join(
                inbound_messages,
                inbound_messages.c.id == work_items.c.inbound_message_id,
            )
            .join(
                claim_orders,
                claim_orders.c.id
                == sa.func.coalesce(inbound_messages.c.order_id, watched_threads.c.claim_order_id),
            )
        )
        .where(
            claim_orders.c.restaurant_id.in_(target_restaurant_ids),
            watched_threads.c.star_active.is_(True),
            watched_threads.c.status.in_(("active", "manual_review")),
        )
        .order_by(
            watched_threads.c.id,
            sa.case((inbound_messages.c.received_at.is_(None), 1), else_=0),
            inbound_messages.c.received_at.desc(),
            inbound_messages.c.id.desc(),
        )
    ).all()

    latest_by_thread: dict[int, object] = {}
    for row in candidate_rows:
        latest_by_thread.setdefault(row.watched_thread_id, row)

    for row in latest_by_thread.values():
        send_requested = bind.execute(
            sa.select(provider_drafts.c.id)
            .select_from(
                appeal_attempts.join(
                    provider_drafts,
                    provider_drafts.c.id == appeal_attempts.c.provider_draft_id,
                )
            )
            .where(
                appeal_attempts.c.based_on_refusal_message_id == row.inbound_message_id,
                provider_drafts.c.status == "send_requested",
            )
            .limit(1)
        ).scalar_one_or_none()
        if send_requested is not None:
            continue
        bind.execute(
            work_items.update()
            .where(work_items.c.id == row.work_item_id)
            .values(
                status="pending",
                reason="restaurant_identity_rename_reanalysis",
                processed_at=None,
                updated_at=now,
            )
        )
        bind.execute(
            inbound_messages.update()
            .where(inbound_messages.c.id == row.inbound_message_id)
            .values(
                review_status="unreviewed",
                reviewed_at=None,
                reviewed_by_user_id=None,
            )
        )
        bind.execute(
            watched_threads.update()
            .where(watched_threads.c.id == row.watched_thread_id)
            .values(status="active", updated_at=now)
        )


def downgrade() -> None:
    # The migration only corrects operational business data. Reverting it could
    # re-enable obsolete Gmail drafts or hide work already completed after deploy.
    pass


def normalized_name(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().replace("(", " ").replace(")", " ").split())

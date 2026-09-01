"""add weekly newsletter subscriptions and delivery ledger

Revision ID: f1a7c3d9e502
Revises: e6b4c9a2f731
Create Date: 2026-09-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a7c3d9e502"
down_revision: Union[str, Sequence[str], None] = "e6b4c9a2f731"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "newsletter_subscribers",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("confirmation_token_hash", sa.String(length=64), nullable=False),
        sa.Column("unsubscribe_token_hash", sa.String(length=64), nullable=False),
        sa.Column("confirmation_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmation_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=80), nullable=False, server_default="weekly_page"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_newsletter_subscribers_email",
        "newsletter_subscribers",
        ["email"],
        unique=True,
    )
    op.create_index(
        "ix_newsletter_subscribers_status",
        "newsletter_subscribers",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_newsletter_subscribers_confirmation_token_hash",
        "newsletter_subscribers",
        ["confirmation_token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_newsletter_subscribers_unsubscribe_token_hash",
        "newsletter_subscribers",
        ["unsubscribe_token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_newsletter_subscribers_confirmed_at",
        "newsletter_subscribers",
        ["confirmed_at"],
        unique=False,
    )

    op.create_table(
        "newsletter_deliveries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subscriber_id", sa.String(length=32), nullable=False),
        sa.Column("period_key", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["subscriber_id"],
            ["newsletter_subscribers.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "subscriber_id",
            "period_key",
            name="uq_newsletter_delivery_subscriber_period",
        ),
    )
    op.create_index(
        "ix_newsletter_deliveries_subscriber_id",
        "newsletter_deliveries",
        ["subscriber_id"],
        unique=False,
    )
    op.create_index(
        "ix_newsletter_deliveries_period_key",
        "newsletter_deliveries",
        ["period_key"],
        unique=False,
    )
    op.create_index(
        "ix_newsletter_deliveries_status",
        "newsletter_deliveries",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_newsletter_deliveries_period_status",
        "newsletter_deliveries",
        ["period_key", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_newsletter_deliveries_period_status", table_name="newsletter_deliveries")
    op.drop_index("ix_newsletter_deliveries_status", table_name="newsletter_deliveries")
    op.drop_index("ix_newsletter_deliveries_period_key", table_name="newsletter_deliveries")
    op.drop_index("ix_newsletter_deliveries_subscriber_id", table_name="newsletter_deliveries")
    op.drop_table("newsletter_deliveries")
    op.drop_index("ix_newsletter_subscribers_confirmed_at", table_name="newsletter_subscribers")
    op.drop_index(
        "ix_newsletter_subscribers_unsubscribe_token_hash",
        table_name="newsletter_subscribers",
    )
    op.drop_index(
        "ix_newsletter_subscribers_confirmation_token_hash",
        table_name="newsletter_subscribers",
    )
    op.drop_index("ix_newsletter_subscribers_status", table_name="newsletter_subscribers")
    op.drop_index("ix_newsletter_subscribers_email", table_name="newsletter_subscribers")
    op.drop_table("newsletter_subscribers")

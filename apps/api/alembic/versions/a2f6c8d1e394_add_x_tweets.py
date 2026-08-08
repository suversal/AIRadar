"""add x_tweets table (SourcePilot Phase 4)

Revision ID: a2f6c8d1e394
Revises: d4e8f1a927c3
Create Date: 2026-08-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a2f6c8d1e394"
down_revision: Union[str, Sequence[str], None] = "d4e8f1a927c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "x_tweets",
        sa.Column("tweet_id", sa.String(), primary_key=True),
        sa.Column("author_handle", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=True),
        sa.Column("tweet_type", sa.String(), nullable=False, server_default="original"),
        sa.Column("content_kind", sa.String(), nullable=False, server_default="brief"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("first_synced_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_x_tweets_author_handle", "x_tweets", ["author_handle"])
    op.create_index("ix_x_tweets_conversation_id", "x_tweets", ["conversation_id"])
    op.create_index("ix_x_tweets_content_kind", "x_tweets", ["content_kind"])
    op.create_index("ix_x_tweets_created_at", "x_tweets", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_x_tweets_created_at", table_name="x_tweets")
    op.drop_index("ix_x_tweets_content_kind", table_name="x_tweets")
    op.drop_index("ix_x_tweets_conversation_id", table_name="x_tweets")
    op.drop_index("ix_x_tweets_author_handle", table_name="x_tweets")
    op.drop_table("x_tweets")

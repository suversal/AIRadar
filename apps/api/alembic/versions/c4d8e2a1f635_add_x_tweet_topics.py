"""add x_tweets.topics column (SP contract 1.9.0 topic subscriptions)

Revision ID: c4d8e2a1f635
Revises: b7e3d9f0c521
Create Date: 2026-08-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d8e2a1f635"
down_revision: Union[str, Sequence[str], None] = "b7e3d9f0c521"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "x_tweets",
        sa.Column("topics", sa.String(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("x_tweets", "topics")

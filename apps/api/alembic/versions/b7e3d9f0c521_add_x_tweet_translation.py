"""add x_tweets.translation column (Plan B: AR-side translation)

Revision ID: b7e3d9f0c521
Revises: a2f6c8d1e394
Create Date: 2026-08-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7e3d9f0c521"
down_revision: Union[str, Sequence[str], None] = "a2f6c8d1e394"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("x_tweets", sa.Column("translation", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("x_tweets", "translation")

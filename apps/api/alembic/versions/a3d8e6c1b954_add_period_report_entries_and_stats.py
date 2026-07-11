"""add period report entries and stats

Revision ID: a3d8e6c1b954
Revises: e1f7a9c8b432
Create Date: 2026-07-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a3d8e6c1b954"
down_revision: Union[str, Sequence[str], None] = "e1f7a9c8b432"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "period_reports",
        sa.Column("entries", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "period_reports",
        sa.Column("stats", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.alter_column("period_reports", "entries", server_default=None)
    op.alter_column("period_reports", "stats", server_default=None)


def downgrade() -> None:
    op.drop_column("period_reports", "stats")
    op.drop_column("period_reports", "entries")

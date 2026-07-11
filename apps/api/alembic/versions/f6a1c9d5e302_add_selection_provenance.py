"""add selection provenance

Revision ID: f6a1c9d5e302
Revises: d8b3f1c4e627
Create Date: 2026-07-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a1c9d5e302"
down_revision: Union[str, Sequence[str], None] = "d8b3f1c4e627"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "processed_articles",
        sa.Column("selection_origin", sa.String(), nullable=False, server_default="score"),
    )
    op.add_column(
        "processed_articles",
        sa.Column("selection_reason", sa.Text(), nullable=True),
    )
    op.alter_column("processed_articles", "selection_origin", server_default=None)


def downgrade() -> None:
    op.drop_column("processed_articles", "selection_reason")
    op.drop_column("processed_articles", "selection_origin")

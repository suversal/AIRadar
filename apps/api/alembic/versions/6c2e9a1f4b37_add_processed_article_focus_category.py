"""add processed article focus category

Revision ID: 6c2e9a1f4b37
Revises: 4a13bfea9a5b
Create Date: 2026-07-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6c2e9a1f4b37"
down_revision: Union[str, Sequence[str], None] = "4a13bfea9a5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "processed_articles",
        sa.Column("focus_category", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_processed_articles_focus_category",
        "processed_articles",
        ["focus_category"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_processed_articles_focus_category",
        table_name="processed_articles",
    )
    op.drop_column("processed_articles", "focus_category")

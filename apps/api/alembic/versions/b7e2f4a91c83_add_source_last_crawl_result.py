"""add source last_crawl_result

Revision ID: b7e2f4a91c83
Revises: a3d8e6c1b954
Create Date: 2026-07-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7e2f4a91c83"
down_revision: Union[str, Sequence[str], None] = "a3d8e6c1b954"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("last_crawl_result", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sources", "last_crawl_result")

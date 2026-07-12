"""add pipeline_runs ingest metrics (new_raw_count, new_selected_count)

台账指标重构(2026-07-12):raw/processed 计数被缓存复用的旧文章淹没,
新列记录本轮真正新入库的文章数和其中最终入选精选的数量。
历史行保持 NULL(而非回填 0),前端显示 --。

Revision ID: c9d4e7f2a615
Revises: b7e2f4a91c83
Create Date: 2026-07-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d4e7f2a615"
down_revision: Union[str, Sequence[str], None] = "b7e2f4a91c83"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pipeline_runs",
        sa.Column("new_raw_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "pipeline_runs",
        sa.Column("new_selected_count", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pipeline_runs", "new_selected_count")
    op.drop_column("pipeline_runs", "new_raw_count")

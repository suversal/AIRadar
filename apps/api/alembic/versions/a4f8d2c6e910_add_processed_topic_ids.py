"""add processed_articles.topic_ids

主题归属列(topics 注册表的 canonical id 列表)。入库时 AI 判定、缺失时
关键词推导;NULL 表示"迁移后未回填的存量行",读取层对 NULL 回退到
关键词匹配,所以这次迁移不带回填——回填由 scripts/backfill_topic_ids.py
单独执行,可重复、可中断。

Revision ID: a4f8d2c6e910
Revises: c7e3a5d9f214
Create Date: 2026-08-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a4f8d2c6e910"
down_revision: Union[str, Sequence[str], None] = "c7e3a5d9f214"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "processed_articles",
        sa.Column("topic_ids", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("processed_articles", "topic_ids")

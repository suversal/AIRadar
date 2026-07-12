"""drop stored non-AI rows; add pipeline_runs.non_ai_dropped_count

产品决策(2026-07-12):非AI文章任何页面都不展示,判定后直接丢弃,
不再为省重复预筛费用而入库。本迁移:
1. 删除存量的 not_ai_related 行(先防御性清理理论上不该存在的派生行);
2. pipeline_runs 增加 non_ai_dropped_count(本轮判非AI直接丢弃的数量),
   台账恒等式:抓取 = 重复 + non_ai_dropped + new_raw。历史行保持 NULL。

Revision ID: d8a1b5c3f942
Revises: c9d4e7f2a615
Create Date: 2026-07-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8a1b5c3f942"
down_revision: Union[str, Sequence[str], None] = "c9d4e7f2a615"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NON_AI_FILTER = "status = 'skipped' AND skipped_reason = 'not_ai_related'"


def upgrade() -> None:
    # 非AI行从未进入 processed/事件/日报,这些派生行理论上不存在;
    # 防御性清理,避免脏数据让外键阻塞删除
    for table, column in (
        ("article_translations", "raw_article_id"),
        ("article_embeddings", "raw_article_id"),
        ("editorial_overrides", "raw_article_id"),
    ):
        op.execute(
            f"DELETE FROM {table} WHERE {column} IN "
            f"(SELECT id FROM raw_articles WHERE {_NON_AI_FILTER})"
        )
    op.execute(f"DELETE FROM raw_articles WHERE {_NON_AI_FILTER}")

    op.add_column(
        "pipeline_runs",
        sa.Column("non_ai_dropped_count", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    # 删除的非AI行不可恢复(它们本就不该存在);只回退新列
    op.drop_column("pipeline_runs", "non_ai_dropped_count")

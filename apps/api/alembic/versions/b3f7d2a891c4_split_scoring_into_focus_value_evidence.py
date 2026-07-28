"""split scoring into ai_focus + value dimensions

Restructures processed_articles' scoring columns to match the new
scoring model (see app.services.scoring_service):
  1. ai_focus (classification: primary/contributing/tangential) replaces
     the continuous ai_relevance dimension - AI-ness is a gate, not a
     weighted-average component.
  2. impact/novelty/substance (value_score) replace the old five value
     dimensions - information_density, actionability and creator_value
     collapsed into a single substance dimension since they were all
     answering "how much usable information does this article carry".
  3. final_score = value_score x a per-source-tier coefficient (T1=1.2,
     T2=1.1, T3=1.0 - boost only, never a penalty) replaces the old
     SOURCE_TIER_WEIGHTS/community_heat_bonus/category_weight/
     freshness_weight multiplier stack.

Historical rows are backfilled with an approximate mapping so they remain
displayable, but this is NOT a re-scoring - the mapped ai_focus/substance
values were never actually judged against the new rubric. Whether to
re-run the new prompt against historical articles is a separate decision.

Revision ID: b3f7d2a891c4
Revises: 6c2e9a1f4b37
Create Date: 2026-07-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3f7d2a891c4"
down_revision: Union[str, Sequence[str], None] = "6c2e9a1f4b37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("processed_articles", sa.Column("ai_focus", sa.String(), nullable=True))
    op.add_column("processed_articles", sa.Column("substance", sa.Float(), nullable=True))

    # ai_focus 过渡映射：沿用旧ai_relevance的三档边界(rubric里9-10/6-8/0-5的
    # 定义)，仅用于让历史数据在新schema下可展示，不代表这些文章被重新判断过
    op.execute(
        """
        UPDATE processed_articles
        SET ai_focus = CASE
            WHEN ai_relevance >= 9 THEN 'primary'
            WHEN ai_relevance >= 6 THEN 'contributing'
            ELSE 'tangential'
        END
        """
    )

    # substance 过渡值：旧三个高度重叠的维度(信息密度/可操作性/创作者价值)的
    # 简单平均，作为合并后单一维度的近似值
    op.execute(
        """
        UPDATE processed_articles
        SET substance = (information_density + actionability + creator_value) / 3.0
        """
    )

    op.alter_column("processed_articles", "ai_focus", nullable=False)
    op.alter_column("processed_articles", "substance", nullable=False)

    op.drop_column("processed_articles", "ai_relevance")
    op.drop_column("processed_articles", "information_density")
    op.drop_column("processed_articles", "actionability")
    op.drop_column("processed_articles", "creator_value")
    op.drop_column("processed_articles", "base_score")


def downgrade() -> None:
    op.add_column("processed_articles", sa.Column("ai_relevance", sa.Float(), nullable=True))
    op.add_column("processed_articles", sa.Column("information_density", sa.Float(), nullable=True))
    op.add_column("processed_articles", sa.Column("actionability", sa.Float(), nullable=True))
    op.add_column("processed_articles", sa.Column("creator_value", sa.Float(), nullable=True))
    op.add_column("processed_articles", sa.Column("base_score", sa.Float(), nullable=True))

    op.execute(
        """
        UPDATE processed_articles
        SET ai_relevance = CASE ai_focus
            WHEN 'primary' THEN 9
            WHEN 'contributing' THEN 7
            ELSE 4
        END,
        information_density = substance,
        actionability = substance,
        creator_value = substance,
        base_score = final_score / 10.0
        """
    )

    op.alter_column("processed_articles", "ai_relevance", nullable=False)
    op.alter_column("processed_articles", "information_density", nullable=False)
    op.alter_column("processed_articles", "actionability", nullable=False)
    op.alter_column("processed_articles", "creator_value", nullable=False)
    op.alter_column("processed_articles", "base_score", nullable=False)

    op.drop_column("processed_articles", "substance")
    op.drop_column("processed_articles", "ai_focus")

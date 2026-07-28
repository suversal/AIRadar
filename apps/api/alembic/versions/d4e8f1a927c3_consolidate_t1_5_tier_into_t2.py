"""consolidate T1_5 source tier into T2

Simplifies the source tier taxonomy from four levels (T1/T1_5/T2/T3) down
to three (T1/T2/T3), matching scoring_service.TIER_COEFFICIENT which no
longer has a T1_5 entry. Existing `sources` rows are admin-authoritative
(see refresh_service.ensure_auto_seeded_sources) - editing
default_sources.py alone would not touch rows already in the database, so
this data migration updates them explicitly.

Revision ID: d4e8f1a927c3
Revises: b3f7d2a891c4
Create Date: 2026-07-28
"""
from typing import Sequence, Union

from alembic import op


revision: str = "d4e8f1a927c3"
down_revision: Union[str, Sequence[str], None] = "b3f7d2a891c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE sources SET tier = 'T2' WHERE tier IN ('T1_5', 'T1.5')")


def downgrade() -> None:
    # 不可逆:降级后无法区分哪些T2信源原本是T1_5——这是一次分类简化决策，
    # 不是可以安全回滚的数据变更。降级留空(no-op)，如果真要回退，需要人工
    # 从default_sources.py原始定义手动核对哪些信源应恢复为T1_5。
    pass

"""remove forced selection from trusted Telegram RSS sources

这三个 RSSHub 信源只应跳过 AI 相关性初筛，后续仍按正常评分阈值决定
是否进入精选。本迁移只删除信源配置中的旧 force_selection=always，
不修改任何历史文章、事件或报告。

Revision ID: e7c4a9d2b681
Revises: d8a1b5c3f942
Create Date: 2026-07-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7c4a9d2b681"
down_revision: Union[str, Sequence[str], None] = "d8a1b5c3f942"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SOURCE_IDS = (
    "telegram_zaihuapd",
    "telegram_xhqcankao",
    "telegram_dnspodt",
)


def _sources_table() -> sa.TableClause:
    return sa.table(
        "sources",
        sa.column("id", sa.String()),
        sa.column("config_json", sa.JSON()),
    )


def upgrade() -> None:
    sources = _sources_table()
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(sources.c.id, sources.c.config_json).where(sources.c.id.in_(_SOURCE_IDS))
    ).mappings()
    for row in rows:
        config = dict(row["config_json"] or {})
        if str(config.get("force_selection") or "").lower() != "always":
            continue
        config.pop("force_selection", None)
        connection.execute(
            sa.update(sources).where(sources.c.id == row["id"]).values(config_json=config)
        )


def downgrade() -> None:
    sources = _sources_table()
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(sources.c.id, sources.c.config_json).where(sources.c.id.in_(_SOURCE_IDS))
    ).mappings()
    for row in rows:
        config = dict(row["config_json"] or {})
        config["force_selection"] = "always"
        connection.execute(
            sa.update(sources).where(sources.c.id == row["id"]).values(config_json=config)
        )

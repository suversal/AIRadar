#!/usr/bin/env python3
"""Realign event_cluster_articles.is_main with event_clusters.main_article_id.

两张表都记着"谁是这个事件的主条"，正常情况下由 upsert_event_clusters 保持
同步(radar_repository.py 的 demote/promote 一段)。同步漏掉时的表现是:详情页
标题来自 main_article_id 指向的那篇,而"主要来源"角标挂在 is_main 标记的另一
篇上——同一个事件说两套话。

修复方向以 event_clusters.main_article_id 为准:它是 choose_main_article 的
产物,也是 _resolve_processed_row 解析事件地址时唯一认的字段。is_main 只是
它在成员表上的投影。

Dry-run 是默认行为,--apply 才落库。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import load_env_file  # noqa: E402
from app.db.models import (  # noqa: E402
    EventClusterArticleModel,
    EventClusterModel,
)
from app.db.session import build_session_factory  # noqa: E402


@dataclass(frozen=True)
class DriftedCluster:
    event_cluster_id: str
    main_article_id: str
    flagged_article_ids: list[str]
    status: str


def inspect_clusters(session: Session) -> list[DriftedCluster]:
    """每个簇比对一次两张表，只返回对不上的。"""
    memberships_by_cluster: dict[str, list[EventClusterArticleModel]] = {}
    for membership in session.scalars(select(EventClusterArticleModel)):
        memberships_by_cluster.setdefault(
            str(membership.event_cluster_id), []
        ).append(membership)

    drifted: list[DriftedCluster] = []
    for cluster in session.scalars(select(EventClusterModel)):
        cluster_id = str(cluster.id)
        main_article_id = str(cluster.main_article_id)
        memberships = memberships_by_cluster.get(cluster_id, [])
        member_ids = {str(item.raw_article_id) for item in memberships}
        flagged = sorted(
            str(item.raw_article_id) for item in memberships if item.is_main
        )
        if flagged == [main_article_id]:
            continue

        if main_article_id not in member_ids:
            # main_article_id 指向一篇根本不在成员表里的文章：投影修不了,
            # 得先弄清楚这个簇的成员为什么少了一篇,不在本脚本职责内。
            status = "main_article_not_a_member"
        elif not flagged:
            status = "no_member_flagged"
        else:
            status = "wrong_member_flagged"
        drifted.append(
            DriftedCluster(
                event_cluster_id=cluster_id,
                main_article_id=main_article_id,
                flagged_article_ids=flagged,
                status=status,
            )
        )
    return drifted


def apply_repairs(session: Session, drifted: list[DriftedCluster]) -> int:
    eligible = [
        item
        for item in drifted
        if item.status in {"no_member_flagged", "wrong_member_flagged"}
    ]
    if not eligible:
        return 0

    repaired = 0
    for item in eligible:
        memberships = list(
            session.scalars(
                select(EventClusterArticleModel).where(
                    EventClusterArticleModel.event_cluster_id == item.event_cluster_id
                )
            )
        )
        # 先降级再提拔，中间 flush 一次：一个事件只能有一个 main 是 DB 层的
        # 部分唯一索引(uq_event_cluster_articles_main)，同一条语句里既有旧
        # main 又有新 main 会直接撞索引。
        for membership in memberships:
            if membership.is_main and str(membership.raw_article_id) != item.main_article_id:
                membership.is_main = False
        session.flush()
        for membership in memberships:
            if str(membership.raw_article_id) == item.main_article_id and not membership.is_main:
                membership.is_main = True
                repaired += 1
        session.flush()
    return repaired


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Realign event_cluster_articles.is_main with event_clusters.main_article_id."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="commit the repair; without this flag the command is read-only",
    )
    args = parser.parse_args()

    load_env_file(ROOT / ".env")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        parser.error("DATABASE_URL is required")

    factory = build_session_factory(database_url)
    with factory() as session:
        before = inspect_clusters(session)
        repaired = apply_repairs(session, before) if args.apply else 0
        if args.apply:
            session.commit()
        else:
            session.rollback()
        after = inspect_clusters(session)
        print(
            json.dumps(
                {
                    "mode": "apply" if args.apply else "dry-run",
                    "drifted_before": len(before),
                    "drifted_after": len(after),
                    "repaired": repaired,
                    "needs_manual_review": sum(
                        item.status == "main_article_not_a_member" for item in after
                    ),
                    "items_before": [asdict(item) for item in before],
                    "items_after": [asdict(item) for item in after],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Retire digest posts that were crawled before the filter existed.

app/services/digest_filter keeps new 早报/晚报/快讯合集 out of the pipeline, but
it only runs when an article is processed. Everything already in the database
stays as it is - including the ones that made a daily report, where they still
show a headline about one story sitting on top of a round-up of a dozen.

What this does to each matching article:

  - raw_articles.status -> skipped, skipped_reason -> digest, matching what the
    live filter would have written had it existed at crawl time
  - deletes its processed_articles row, so it disappears from every surface
    (all site reads join through that table; a skipped article with no scoring
    row is exactly the state the filter produces)
  - deletes its daily_report_entries rows, so the days it appeared in no longer
    list it

Deliberately not done here: regenerating the affected days' AI summaries. Their
summary_digest no longer matches the day's material, so the next pipeline run
rewrites them on its own; forcing it here would buy the same text twice. Run
scripts/backfill_daily_summaries.py if you want them refreshed immediately.

Event clusters are cleaned up too, because a digest that keeps a cluster row
alive keeps the event alive. Measured here: 31 of the 32 affected clusters hold
the digest and nothing else, and are deleted outright; one holds a second,
real article, so the digest is removed from it and the survivor is promoted to
main. Clustering does get fooled by digests - that two-member cluster paired
「IT早报 0817」 with 「问界儿童车官宣即将上市」, a car story it happened to list -
which is one more reason not to carry them.

Usage:
    .venv/bin/python scripts/purge_digest_articles.py
    .venv/bin/python scripts/purge_digest_articles.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sqlalchemy import delete, select  # noqa: E402

from app.db.models import (  # noqa: E402
    DailyReportEntryModel,
    EventClusterArticleModel,
    EventClusterModel,
    ProcessedArticleModel,
    RawArticleModel,
)
from app.services.digest_filter import is_digest_title  # noqa: E402


def find_digests(session) -> list[dict]:
    rows = session.execute(
        select(RawArticleModel.id, RawArticleModel.title, RawArticleModel.status)
    ).all()
    found = []
    for raw_id, title, status in rows:
        if not is_digest_title(title):
            continue
        processed = session.scalar(
            select(ProcessedArticleModel).where(
                ProcessedArticleModel.raw_article_id == raw_id
            )
        )
        entries = session.scalars(
            select(DailyReportEntryModel.report_date).where(
                DailyReportEntryModel.raw_article_id == raw_id
            )
        ).all()
        found.append(
            {
                "raw_id": raw_id,
                "title": title,
                "status": status,
                "was_selected": bool(processed and processed.status == "processed"),
                "has_processed": processed is not None,
                "clustered": bool(processed and processed.event_cluster_id),
                "report_dates": [d.isoformat() for d in entries],
            }
        )
    return found


def purge(session, digests: list[dict]) -> dict[str, int]:
    stats = {"clusters_deleted": 0, "clusters_repointed": 0}
    for row in digests:
        raw_id = row["raw_id"]
        session.execute(
            delete(DailyReportEntryModel).where(
                DailyReportEntryModel.raw_article_id == raw_id
            )
        )
        # 打分行必须先删：processed_articles.event_cluster_id 有外键指向
        # event_clusters，留着它去删簇会直接撞 ForeignKeyViolation。
        cluster_ids = session.scalars(
            select(EventClusterArticleModel.event_cluster_id).where(
                EventClusterArticleModel.raw_article_id == raw_id
            )
        ).all()
        session.execute(
            delete(ProcessedArticleModel).where(
                ProcessedArticleModel.raw_article_id == raw_id
            )
        )
        session.flush()
        for cluster_id in list(
            cluster_ids
        ):
            session.execute(
                delete(EventClusterArticleModel).where(
                    EventClusterArticleModel.event_cluster_id == cluster_id,
                    EventClusterArticleModel.raw_article_id == raw_id,
                )
            )
            session.flush()
            survivors = session.scalars(
                select(EventClusterArticleModel.raw_article_id).where(
                    EventClusterArticleModel.event_cluster_id == cluster_id
                )
            ).all()
            cluster = session.get(EventClusterModel, cluster_id)
            if cluster is None:
                continue
            if not survivors:
                session.delete(cluster)
                stats["clusters_deleted"] += 1
                continue
            if cluster.main_article_id == raw_id:
                # 主文被删了，把剩下的成员里分最高的那篇提上来
                best = max(
                    survivors,
                    key=lambda rid: float(
                        getattr(
                            session.scalar(
                                select(ProcessedArticleModel).where(
                                    ProcessedArticleModel.raw_article_id == rid
                                )
                            ),
                            "final_score",
                            0.0,
                        )
                        or 0.0
                    ),
                )
                cluster.main_article_id = best
                stats["clusters_repointed"] += 1
            cluster.source_count = max(len(survivors), 1)
        raw = session.get(RawArticleModel, raw_id)
        if raw is not None:
            raw.status = "skipped"
            raw.skipped_reason = "digest"
    session.commit()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--apply", action="store_true", help="write the changes")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")

    from app.db.session import build_session_factory

    session = build_session_factory(args.database_url)()
    try:
        digests = find_digests(session)
        affected_days = sorted({d for row in digests for d in row["report_dates"]})
        clustered = [row for row in digests if row["clustered"]]

        print(f"命中合集 {len(digests)} 篇")
        print(f"  其中曾入选日报 {sum(1 for r in digests if r['was_selected'])} 篇")
        print(f"  已有打分行（会被删除）{sum(1 for r in digests if r['has_processed'])} 篇")
        print(f"  受影响的日报日期 {len(affected_days)} 天: {', '.join(affected_days)}")
        if clustered:
            print(f"  被聚进事件簇的 {len(clustered)} 篇：只含它自己的簇会被删除，")
            print("    还有其他成员的簇改由剩下分最高的那篇当主文")

        print("\n曾进过日报的：")
        for row in digests:
            if row["report_dates"]:
                print(f"  {','.join(row['report_dates'])}  {row['title'][:64]}")

        if args.apply:
            stats = purge(session, digests)
            print(f"\n已处理 {len(digests)} 篇。")
            print(
                f"事件簇：删除 {stats['clusters_deleted']} 个（只含合集本身），"
                f"改主文 {stats['clusters_repointed']} 个（还有其他成员）。"
            )
            print("受影响日期的日报摘要指纹已失效，下次流水线运行会自行重写；")
            print("想立刻刷新就跑 scripts/backfill_daily_summaries.py。")
        else:
            print("\ndry run：未写入。加 --apply 执行。")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

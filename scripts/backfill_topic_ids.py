"""回填 processed_articles.topic_ids(主题归属)。

用注册表关键词对 标题+一句话提要+tags 推导 canonical id 列表——和
读取层对 NULL 行的兜底逻辑(topics._keywords_match_item)完全同源,
所以回填前后读者看到的归属不变,变的只是查询以后能下推 SQL。

默认只写 NULL 行(可重复、可中断);--force 重算所有行——注册表关键词
改过之后想让存量跟上时用,注意它会覆盖 AI 判定的行,谨慎。

用法:
    python scripts/backfill_topic_ids.py [--force] [--dry-run]
    DATABASE_URL 缺省取 postgresql+psycopg://radar:radar@localhost:5432/radar
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import ProcessedArticleModel
from app.services.topics import derive_topic_ids

BATCH = 500


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="重算所有行(会覆盖 AI 判定)")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = parser.parse_args()

    database_url = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://radar:radar@localhost:5432/radar"
    )
    engine = create_engine(database_url)

    updated = 0
    scanned = 0
    with Session(engine) as session:
        query = select(ProcessedArticleModel)
        if not args.force:
            query = query.where(ProcessedArticleModel.topic_ids.is_(None))
        rows = session.scalars(query).all()
        for model in rows:
            scanned += 1
            topic_ids = derive_topic_ids(
                {
                    "title": model.title_zh or "",
                    "one_line_summary": model.one_line_summary or "",
                    "tags": model.tags or [],
                }
            )
            model.topic_ids = topic_ids
            updated += 1
            if not args.dry_run and updated % BATCH == 0:
                session.commit()
        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    mode = "dry-run,未写库" if args.dry_run else "已写库"
    print(f"扫描 {scanned} 行,回填 {updated} 行({mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

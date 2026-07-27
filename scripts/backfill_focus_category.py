#!/usr/bin/env python3
"""Backfill the four-way reader focus without touching scores or selection.

Examples:
    .venv/bin/python scripts/backfill_focus_category.py \
        --database-url postgresql+psycopg://radar:radar@localhost:5432/radar \
        --days 30 --dry-run

    .venv/bin/python scripts/backfill_focus_category.py \
        --database-url postgresql+psycopg://radar:radar@localhost:5432/radar \
        --days 90
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from sqlalchemy import select  # noqa: E402

from app.db.models import ProcessedArticleModel, RawArticleModel  # noqa: E402
from app.db.session import build_session_factory, session_scope  # noqa: E402
from app.services.taxonomy import infer_focus_category  # noqa: E402


def _classification_text(processed: ProcessedArticleModel, raw: RawArticleModel) -> str:
    return " ".join(
        [
            str(processed.title_zh or raw.title or ""),
            str(processed.one_line_summary or ""),
            str(processed.summary_zh or ""),
            " ".join(str(tag) for tag in processed.tags or []),
        ]
    )


def backfill(
    session,
    *,
    days: int,
    limit: int | None,
    dry_run: bool,
    overwrite: bool,
    scoring_category: str | None = None,
) -> dict[str, object]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    query = (
        select(ProcessedArticleModel, RawArticleModel)
        .join(
            RawArticleModel,
            RawArticleModel.id == ProcessedArticleModel.raw_article_id,
        )
        .where(RawArticleModel.published_at >= cutoff)
        .order_by(RawArticleModel.published_at.desc())
    )
    if not overwrite:
        query = query.where(ProcessedArticleModel.focus_category.is_(None))
    if scoring_category is not None:
        query = query.where(ProcessedArticleModel.category == scoring_category)
    if limit is not None:
        query = query.limit(limit)

    rows = session.execute(query).all()
    distribution: Counter[str] = Counter()
    updated = 0
    unresolved = 0
    for processed, raw in rows:
        focus = infer_focus_category(
            processed.category,
            text=_classification_text(processed, raw),
        )
        if focus is None:
            unresolved += 1
            distribution["unresolved"] += 1
            continue
        distribution[focus] += 1
        if processed.focus_category != focus:
            updated += 1
            if not dry_run:
                processed.focus_category = focus

    return {
        "days": days,
        "dry_run": dry_run,
        "overwrite": overwrite,
        "scoring_category": scoring_category,
        "examined": len(rows),
        "would_update" if dry_run else "updated": updated,
        "unresolved": unresolved,
        "distribution": dict(sorted(distribution.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill processed_articles.focus_category only."
    )
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Recompute rows that already have focus_category.",
    )
    parser.add_argument(
        "--scoring-category",
        help="Only process rows whose 8-way scoring category equals this value "
        "(e.g. 'tutorial'). Combine with --overwrite for a narrow recompute "
        "that does not touch other categories.",
    )
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")
    if args.days < 1 or args.days > 3650:
        parser.error("--days must be between 1 and 3650")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")

    session_factory = build_session_factory(args.database_url)
    with session_scope(session_factory) as session:
        result = backfill(
            session,
            days=args.days,
            limit=args.limit,
            dry_run=args.dry_run,
            overwrite=args.overwrite,
            scoring_category=args.scoring_category,
        )
        if args.dry_run:
            session.rollback()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

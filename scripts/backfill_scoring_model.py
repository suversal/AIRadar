"""Backfill processed_articles.model_used for articles scored before the column
was ever written.

model_used only started being recorded on 2026-08-17. Everything scored before
that is NULL, which matters because周月报 now ranks within scoring-model groups
(app/api/public.py sort_period_items): with the whole history in one anonymous
group, 2026-08 keeps ranking DeepSeek-era and Qwen-era items against each other
on raw score, which is exactly the defect the grouping exists to fix.

Which model scored a row is *not* recoverable from processed_articles.pipeline_run_id:
that column is overwritten by every later run that touches the article, including
runs that only reused a cached score. What is recoverable is *when* the row was
first written - created_at is set on INSERT and no later run moves it - and the
provider in use at that moment.

ai_usage_stats records provider/model per scoring call, so the switchover moments
are read out of it rather than hardcoded here. That table only goes back to
2026-08-13 (the telemetry landed in the same commit as the DeepSeek -> Qwen
switch, so it happens to straddle it), and everything older belongs to whatever
ran before it: one provider for the project's entire prior history, named
explicitly via --legacy-model so the assumption is stated rather than buried.

Rows already carrying a model_used are never touched - a recorded value is
evidence, this script's inference is not.

created_at is only a proxy for scoring time: a row created before a switch and
re-scored after it would be mislabelled. Measured on this database before the
first run, that gap is empty - of the 4673 pre-switch rows this script would
write, zero had been updated at all since the switch, so none of them can have
been re-scored. (Five rows *were* re-scored across the boundary, and all five
already carry a recorded model_used, so they fall outside what this touches.)
Re-check that count before trusting a run on a database this was not measured on.

Usage:
    .venv/bin/python scripts/backfill_scoring_model.py
    .venv/bin/python scripts/backfill_scoring_model.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from sqlalchemy import func, select, text  # noqa: E402

from app.db.models import AIUsageStatModel, ProcessedArticleModel  # noqa: E402

SCORING_OPERATION = "score_article"


def scoring_segments(session) -> list[tuple[datetime, str]]:
    """(from_time, model) for every recorded change of scoring model, in order.

    Collapses consecutive calls by the same model into one segment, so a
    provider that ran for days yields one row rather than thousands.
    """
    rows = session.execute(
        select(AIUsageStatModel.recorded_at, AIUsageStatModel.model)
        .where(AIUsageStatModel.operation == SCORING_OPERATION)
        .order_by(AIUsageStatModel.recorded_at.asc())
    ).all()
    segments: list[tuple[datetime, str]] = []
    for recorded_at, model in rows:
        if not segments or segments[-1][1] != model:
            segments.append((recorded_at, model))
    return segments


def model_at(segments: list[tuple[datetime, str]], moment: datetime, legacy_model: str) -> str:
    """The scoring model in use at `moment`; legacy_model before records begin."""
    chosen = legacy_model
    for start, model in segments:
        if moment >= start:
            chosen = model
        else:
            break
    return chosen


def plan(session, *, legacy_model: str) -> dict[str, int]:
    segments = scoring_segments(session)
    rows = session.execute(
        select(ProcessedArticleModel.raw_article_id, ProcessedArticleModel.created_at).where(
            ProcessedArticleModel.model_used.is_(None)
        )
    ).all()
    assignments: dict[str, str] = {}
    for raw_article_id, created_at in rows:
        assignments[raw_article_id] = model_at(segments, created_at, legacy_model)
    counts: dict[str, int] = {}
    for model in assignments.values():
        counts[model] = counts.get(model, 0) + 1
    return {"segments": segments, "assignments": assignments, "counts": counts}


def apply(session, assignments: dict[str, str]) -> int:
    for raw_article_id, model in assignments.items():
        session.execute(
            text(
                "UPDATE processed_articles SET model_used = :model "
                "WHERE raw_article_id = :raw_article_id AND model_used IS NULL"
            ),
            {"model": model, "raw_article_id": raw_article_id},
        )
    session.commit()
    return len(assignments)


def score_range_by_model(session) -> list[tuple[str, int, float, float]]:
    """Per-model (count, min, max) final_score, printed as the after-the-fact
    read on what the grouping now separates.

    Note the ranges overlap: Qwen scored two articles 96.0 and 100.0 on the
    afternoon it took over. The scales differ in their *distribution*, not by a
    hard ceiling - which is the whole reason周月报 compares rank-within-model
    instead of raw score.
    """
    rows = session.execute(
        select(
            ProcessedArticleModel.model_used,
            func.count(),
            func.min(ProcessedArticleModel.final_score),
            func.max(ProcessedArticleModel.final_score),
        ).group_by(ProcessedArticleModel.model_used)
    ).all()
    return [(model or "(未标注)", count, low, high) for model, count, low, high in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument(
        "--legacy-model",
        default="deepseek-v4-flash",
        help="model that scored everything older than the earliest ai_usage_stats record",
    )
    parser.add_argument("--apply", action="store_true", help="write the inferred model names")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")

    from app.db.session import build_session_factory

    session = build_session_factory(args.database_url)()
    try:
        result = plan(session, legacy_model=args.legacy_model)
        print("记录在案的打分模型切换点：")
        for start, model in result["segments"]:
            print(f"  {start.isoformat()}  ->  {model}")
        if not result["segments"]:
            print(f"  （ai_usage_stats 里没有 {SCORING_OPERATION} 记录）")
        print(f"\n待回填 {len(result['assignments'])} 行：")
        for model, count in sorted(result["counts"].items()):
            print(f"  {model:20s} {count}")

        if args.apply:
            written = apply(session, result["assignments"])
            print(f"\n已写入 {written} 行。")
        else:
            print("\ndry run：未写入。加 --apply 执行。")

        print("\n各模型的分数区间（用来核对边界是否切对）：")
        for model, count, low, high in sorted(score_range_by_model(session)):
            print(f"  {model:20s} n={count:<6d} {low:.1f} ~ {high:.1f}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

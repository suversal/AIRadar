"""Re-generate weekly/monthly reports for a date range.

Needed after anything that changes what the days' daily reports contain - the
2026-08 event-merge backfill being the case this was written for. A period
report is a rollup of its days' *published daily reports*, and its AI mainline
is prose written from those items, so merging fragments into single events does
not update the text on its own.

Each (kind, period_key) in range is regenerated exactly once. The naive approach
- calling refresh_service._regenerate_period_reports for every date - would
rewrite the same monthly report once per day in the range, paying for a
long-form AI call every time.

Reuses the same read path as production (build_period_payload over persisted
daily reports), so an event that was scored but never published in any daily
report stays out of the rollup.

Usage:
    .venv/bin/python scripts/regenerate_period_reports.py --since 2026-08-01 --until 2026-08-18
    .venv/bin/python scripts/regenerate_period_reports.py --since 2026-08-01 --until 2026-08-18 --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.api.public import build_period_payload  # noqa: E402
from app.repositories.radar_repository import RadarRepository  # noqa: E402
from app.services.period_summary_service import (  # noqa: E402
    build_period_report,
    period_key_for,
    period_range_for_key,
)


def targets_for(since: date, until: date) -> list[tuple[str, str]]:
    """Every (kind, period_key) touching [since, until), each exactly once."""
    seen: list[tuple[str, str]] = []
    day = since
    while day < until:
        for kind in ("weekly", "monthly"):
            target = (kind, period_key_for(kind, day))
            if target not in seen:
                seen.append(target)
        day += timedelta(days=1)
    return seen


def regenerate(
    session,
    targets: list[tuple[str, str]],
    *,
    ai_provider,
    apply: bool,
    force: bool = False,
    today: date | None = None,
) -> list[dict]:
    repository = RadarRepository(session)
    today = today or date.today()
    results = []
    for kind, key in targets:
        range_start, range_end = period_range_for_key(kind, key)
        stored = repository.get_period_report(kind, key)
        # 已封版的期次是定稿，默认不碰；--force 是编辑决定重写（比如这次
        # 换了报告结构），重写完仍然是定稿
        if stored and stored.get("finalized_at") and not force:
            results.append(
                {"kind": kind, "key": key, "status": "skipped-finalized", "items": 0}
            )
            continue
        daily_payloads = repository.get_daily_report_payloads_between(range_start, range_end)
        merged = build_period_payload(
            daily_payloads, mode=kind, range_start=range_start, range_end=range_end
        )
        if not merged["items"]:
            results.append({"kind": kind, "key": key, "status": "skipped-empty", "items": 0})
            continue
        if not apply:
            results.append(
                {
                    "kind": kind,
                    "key": key,
                    "status": "would-regenerate",
                    "items": len(merged["items"]),
                }
            )
            continue
        # anchor must fall inside the period it names; range_start always does
        report = build_period_report(
            kind=kind,
            anchor=range_start,
            items=merged["items"],
            report_dates=sorted(merged["report_dates"]),
            ai_provider=ai_provider,
            # digest 复用照常生效：素材和输入结构都没变的期次不重买
            previous=stored,
            # 已经翻篇的期次这一遍就是它的收尾：直接封版，交还给刷新
            # 流水线也只会被 finalized_at 跳过，没有第二次机会了
            finalize=range_end < today,
        )
        repository.upsert_period_report(report)
        session.commit()
        results.append(
            {
                "kind": kind,
                "key": key,
                "status": report["status"],
                "items": report["article_count"],
                "body_chars": len(report["mainline_body"]),
                "title": report["mainline_title"],
                "finalized": bool(report.get("finalized_at")),
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--since", required=True)
    parser.add_argument("--until", required=True)
    parser.add_argument("--apply", action="store_true", help="write the regenerated reports")
    parser.add_argument(
        "--force",
        action="store_true",
        help="regenerate even finalized periods (they stay finalized afterwards)",
    )
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")

    from app.db.session import build_session_factory
    from app.services.ai_service import provider_from_env

    since = date.fromisoformat(args.since)
    until = date.fromisoformat(args.until)
    targets = targets_for(since, until)
    ai_provider = provider_from_env() if args.apply else None

    session = build_session_factory(args.database_url)()
    try:
        results = regenerate(
            session, targets, ai_provider=ai_provider, apply=args.apply, force=args.force
        )
    finally:
        session.close()

    for row in results:
        extra = ""
        if "body_chars" in row:
            seal = " [封版]" if row.get("finalized") else ""
            extra = f" body={row['body_chars']}字 「{row['title'][:28]}」{seal}"
        print(f"{row['kind']:8s} {row['key']:9s} {row['status']:16s} items={row['items']}{extra}")
    fallbacks = [row for row in results if row["status"] == "fallback"]
    if fallbacks:
        print(f"\n{len(fallbacks)} period(s) still degraded to the deterministic fallback")
        return 1
    if not args.apply:
        print("\ndry run: nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

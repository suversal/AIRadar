"""Generate the AI mainline and category notes for daily reports that predate
the feature.

New daily reports get theirs from the pipeline (refresh_service
._regenerate_daily_summary). Reports written before 2026-08-18 have none, so
their 今日看点 rows fall back to showing each category's top headline instead
of a written note - readable, but not what the page is now for.

Reads the resolved daily payload, the same one the page reads, so the summary
is written from exactly the events a reader sees. Days with no multi-source
event get no mainline by design (see daily_summary_service) and are reported
as skipped rather than filled with invented copy.

Already-summarised days are left alone unless --force: the material
fingerprint makes a re-run free to attempt, but re-buying identical text is
still waste.

Usage:
    .venv/bin/python scripts/backfill_daily_summaries.py --since 2026-07-15 --until 2026-08-19
    .venv/bin/python scripts/backfill_daily_summaries.py --since 2026-07-15 --until 2026-08-19 --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.repositories.radar_repository import RadarRepository  # noqa: E402
from app.services.daily_summary_service import (  # noqa: E402
    build_daily_summary,
    build_summary_input,
    is_multi_source,
)


def backfill(session, days: list[date], *, ai_provider, apply: bool, force: bool) -> list[dict]:
    repository = RadarRepository(session)
    results: list[dict] = []
    for day in days:
        payload = repository.get_daily_report_payload(day)
        if not payload or not payload.get("items"):
            continue
        items = payload["items"]
        multi = sum(1 for item in items if is_multi_source(item))
        if not apply:
            summary_input = build_summary_input(items)
            stored = (payload.get("summary_status") or "pending") == "generated"
            status = (
                "skipped-no-multi-source"
                if not summary_input["mainline_events"]
                else "already-generated"
                if stored and not force
                else "would-generate"
            )
            results.append({"day": day, "status": status, "items": len(items), "multi": multi})
            continue

        summary = build_daily_summary(
            report_date=day,
            items=items,
            ai_provider=ai_provider,
            previous_digest=None if force else repository.get_daily_summary_digest(day),
        )
        if summary is None:
            results.append({"day": day, "status": "unchanged", "items": len(items), "multi": multi})
            continue
        repository.upsert_daily_summary(day, summary)
        session.commit()
        results.append(
            {
                "day": day,
                "status": summary["status"],
                "items": len(items),
                "multi": multi,
                "body_chars": len(summary["mainline_body"]),
                "notes": len(summary["category_notes"]),
                "title": summary["mainline_title"],
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--since", required=True)
    parser.add_argument("--until", required=True, help="exclusive")
    parser.add_argument("--apply", action="store_true", help="write the generated summaries")
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-buy text for days that already have a summary",
    )
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or DATABASE_URL is required")

    from app.db.session import build_session_factory
    from app.services.ai_service import provider_from_env

    since = date.fromisoformat(args.since)
    until = date.fromisoformat(args.until)
    days = []
    day = since
    while day < until:
        days.append(day)
        day += timedelta(days=1)

    session = build_session_factory(args.database_url)()
    try:
        results = backfill(
            session,
            days,
            ai_provider=provider_from_env() if args.apply else None,
            apply=args.apply,
            force=args.force,
        )
    finally:
        session.close()

    for row in results:
        extra = ""
        if "body_chars" in row:
            extra = f" 主线{row['body_chars']}字 简述{row['notes']}条 「{row['title'][:26]}」"
        print(
            f"{row['day']} {row['status']:24s} 条目={row['items']:<3d} 多信源={row['multi']:<2d}{extra}"
        )
    failed = [row for row in results if row["status"] == "failed"]
    if failed:
        print(f"\n{len(failed)} 天生成失败，页面上这些天不会显示主线")
        return 1
    if not args.apply:
        print("\ndry run：未写入。加 --apply 执行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

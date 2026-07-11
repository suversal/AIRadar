"""Period (weekly/monthly) report building with AI mainline summaries.

A period report is the aggregation of the interval's daily reports plus an
AI-written mainline: what the interval was really about. Pure aggregation
without the mainline is just a longer daily report, so the summary is the
point of this module; provider failures degrade to a deterministic
fallback instead of blocking report generation.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

from app.api.public import month_range

SUMMARY_ITEM_LIMIT = 40

_WEEK_KEY_RE = re.compile(r"^(\d{4})-W(\d{2})$")
_MONTH_KEY_RE = re.compile(r"^(\d{4})-(\d{2})$")


def period_key_for(kind: str, anchor: date) -> str:
    if kind == "weekly":
        iso = anchor.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if kind == "monthly":
        return f"{anchor.year}-{anchor.month:02d}"
    raise ValueError(f"unknown period kind: {kind}")


def period_range_for_key(kind: str, key: str) -> tuple[date, date]:
    if kind == "weekly":
        match = _WEEK_KEY_RE.match(key or "")
        if not match:
            raise ValueError(f"invalid weekly key: {key!r}")
        year, week = int(match.group(1)), int(match.group(2))
        start = date.fromisocalendar(year, week, 1)
        end = date.fromisocalendar(year, week, 7)
        return start, end
    if kind == "monthly":
        match = _MONTH_KEY_RE.match(key or "")
        if not match:
            raise ValueError(f"invalid monthly key: {key!r}")
        year, month = int(match.group(1)), int(match.group(2))
        if not 1 <= month <= 12:
            raise ValueError(f"invalid monthly key: {key!r}")
        return month_range(date(year, month, 1))
    raise ValueError(f"unknown period kind: {kind}")


def parse_period_summary_payload(payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("mainline_title") or "").strip()
    body = str(payload.get("mainline_body") or "").strip()
    if not title or not body:
        raise ValueError("period summary payload missing mainline_title/mainline_body")
    theme_notes = []
    for note in payload.get("theme_notes") or []:
        if not isinstance(note, dict):
            continue
        label = str(note.get("label") or "").strip()
        text = str(note.get("note") or "").strip()
        if label and text:
            theme_notes.append({"label": label, "note": text})
    return {"mainline_title": title, "mainline_body": body, "theme_notes": theme_notes}


def _summary_input(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(items, key=lambda item: float(item.get("final_score") or 0.0), reverse=True)
    return [
        {
            "title": str(item.get("title") or "")[:80],
            "summary": str(item.get("one_line_summary") or item.get("summary") or "")[:120],
            "category": str(item.get("category") or ""),
        }
        for item in ranked[:SUMMARY_ITEM_LIMIT]
    ]


def _fallback_summary(kind: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    label = "本周" if kind == "weekly" else "本月"
    top = sorted(items, key=lambda item: float(item.get("final_score") or 0.0), reverse=True)
    top_title = str(top[0].get("title")) if top else "AI 动态"
    return {
        "mainline_title": f"{label} AI 动态一览",
        "mainline_body": (
            f"{label}共收录 {len(items)} 条 AI 动态，代表事件包括「{top_title}」等。"
            "本期 AI 综述生成失败，以上为自动概要；下次日报刷新时将重试。"
        ),
        "theme_notes": [],
    }


def _entries_snapshot(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Freeze which events were selected, in what order, and their score at
    generation time. Content (title/summary/reason/tags/...) is deliberately
    excluded - it is always resolved live from event_id at read time, same
    as daily_report_entries."""
    ranked = sorted(items, key=lambda item: float(item.get("final_score") or 0.0), reverse=True)
    return [
        {
            "event_id": item.get("event_id"),
            "score_at_selection": float(item.get("final_score") or 0.0),
        }
        for item in ranked
        if item.get("event_id")
    ]


def _stats_snapshot(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate counts computed once at generation time so they stop
    changing once the period has rolled over, instead of being recomputed
    (and drifting) on every read."""
    source_ids = {
        item["main_source"]["id"]
        for item in items
        if isinstance(item.get("main_source"), dict) and item["main_source"].get("id")
    }
    multi_source_count = sum(1 for item in items if int(item.get("source_count") or 1) > 1)
    category_distribution: dict[str, int] = {}
    for item in items:
        label = str(item.get("category_label") or item.get("category") or "其他")
        category_distribution[label] = category_distribution.get(label, 0) + 1
    return {
        "source_coverage_count": len(source_ids),
        "multi_source_ratio": (multi_source_count / len(items)) if items else 0.0,
        "category_distribution": category_distribution,
    }


def build_period_report(
    *,
    kind: str,
    anchor: date,
    items: list[dict[str, Any]],
    report_dates: list[str],
    ai_provider: Any,
) -> dict[str, Any]:
    key = period_key_for(kind, anchor)
    range_start, range_end = period_range_for_key(kind, key)
    range_label = f"{range_start.isoformat()} ~ {range_end.isoformat()}"

    status = "generated"
    try:
        summary = ai_provider.summarize_period(_summary_input(items), kind, range_label)
        summary = parse_period_summary_payload(summary)
    except Exception:
        summary = _fallback_summary(kind, items)
        status = "fallback"

    return {
        "kind": kind,
        "period_key": key,
        "range_start": range_start.isoformat(),
        "range_end": range_end.isoformat(),
        "mainline_title": summary["mainline_title"],
        "mainline_body": summary["mainline_body"],
        "theme_notes": summary["theme_notes"],
        "article_count": len(items),
        "report_dates": list(report_dates),
        "entries": _entries_snapshot(items),
        "stats": _stats_snapshot(items),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
    }

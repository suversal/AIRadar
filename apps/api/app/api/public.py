from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any

WEEK_DAYS = 7


def week_range(anchor: date) -> tuple[date, date]:
    return anchor - timedelta(days=WEEK_DAYS - 1), anchor


def month_range(anchor: date) -> tuple[date, date]:
    last_day = calendar.monthrange(anchor.year, anchor.month)[1]
    return anchor.replace(day=1), anchor.replace(day=last_day)


def _merge_daily_items(daily_payloads: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str], str | None]:
    ordered = sorted(daily_payloads, key=lambda payload: payload.get("report_date") or "")
    report_dates: list[str] = []
    updated_at: str | None = None
    merged: dict[str, dict[str, Any]] = {}
    for payload in ordered:
        report_date = payload.get("report_date")
        if report_date:
            report_dates.append(report_date)
        payload_updated = payload.get("updated_at")
        if payload_updated and (updated_at is None or payload_updated > updated_at):
            updated_at = payload_updated
        for item in payload.get("items", []):
            event_id = item.get("event_id") or item.get("original_url") or item.get("title")
            if event_id is None:
                continue
            # later report dates win so corrections in newer dailies replace old copies
            merged[str(event_id)] = item
    return list(merged.values()), report_dates, updated_at


def _item_matches(item: dict[str, Any], *, category: str | None, q: str | None) -> bool:
    if category and item.get("category") != category:
        return False
    if q:
        needle = q.lower()
        haystack = " ".join(
            str(value)
            for value in [
                item.get("title"),
                item.get("one_line_summary"),
                item.get("summary"),
                " ".join(item.get("tags") or []),
                (item.get("main_source") or {}).get("name"),
            ]
            if value
        ).lower()
        if needle not in haystack:
            return False
    return True


def _published_sort_key(item: dict[str, Any]) -> str:
    return str(item.get("published_at") or "")


def build_events_payload(
    daily_payloads: list[dict[str, Any]],
    *,
    category: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    items, report_dates, updated_at = _merge_daily_items(daily_payloads)
    filtered = [item for item in items if _item_matches(item, category=category, q=q)]
    filtered.sort(key=_published_sort_key, reverse=True)
    page = filtered[offset : offset + limit]
    return {
        "report_dates": report_dates,
        "updated_at": updated_at,
        "total": len(filtered),
        "limit": limit,
        "offset": offset,
        "article_count": len(page),
        "items": page,
    }


def build_events_payload_from_items(
    items: list[dict[str, Any]],
    *,
    category: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    filtered = [item for item in items if _item_matches(item, category=category, q=q)]
    filtered.sort(key=_published_sort_key, reverse=True)
    page = filtered[offset : offset + limit]
    updated_at = max(
        (str(item.get("published_at")) for item in filtered if item.get("published_at")),
        default=None,
    )
    return {
        "report_dates": [],
        "updated_at": updated_at,
        "total": len(filtered),
        "limit": limit,
        "offset": offset,
        "article_count": len(page),
        "items": page,
    }


def build_period_payload(
    daily_payloads: list[dict[str, Any]],
    *,
    mode: str,
    range_start: date,
    range_end: date,
) -> dict[str, Any]:
    items, report_dates, updated_at = _merge_daily_items(daily_payloads)
    items.sort(key=lambda item: float(item.get("final_score") or 0.0), reverse=True)
    return {
        "mode": mode,
        "range_start": range_start.isoformat(),
        "range_end": range_end.isoformat(),
        "report_dates": report_dates,
        "updated_at": updated_at,
        "article_count": len(items),
        "items": items,
    }


def build_empty_daily_payload(report_date: date | None = None) -> dict[str, Any]:
    return {
        "report_date": report_date.isoformat() if report_date else None,
        "title": "Suversal AI Radar 日报",
        "summary": "No report generated yet.",
        "updated_at": None,
        "generated_at": None,
        "latest_published_at": None,
        "sections": {},
        "items": [],
        "article_count": 0,
    }


def build_latest_payload(daily_report_json: dict[str, Any]) -> dict[str, Any]:
    return {
        "report_date": daily_report_json.get("report_date"),
        "updated_at": daily_report_json.get("updated_at"),
        "article_count": daily_report_json.get("article_count", len(daily_report_json.get("items", []))),
        "items": daily_report_json.get("items", []),
    }


def build_daily_payload(daily_report_json: dict[str, Any]) -> dict[str, Any]:
    return {
        "report_date": daily_report_json["report_date"],
        "title": daily_report_json["title"],
        "summary": daily_report_json["summary"],
        "updated_at": daily_report_json.get("updated_at"),
        "generated_at": daily_report_json.get("generated_at"),
        "latest_published_at": daily_report_json.get("latest_published_at"),
        "sections": daily_report_json["sections"],
        "items": daily_report_json["items"],
        "article_count": daily_report_json["article_count"],
    }


def build_latest_payload_from_repository(repository: Any) -> dict[str, Any]:
    daily_report_json = repository.get_latest_daily_report_payload()
    if daily_report_json is None:
        daily_report_json = build_empty_daily_payload()
    return build_latest_payload(daily_report_json)


def build_daily_payload_from_repository(repository: Any, report_date: date) -> dict[str, Any]:
    daily_report_json = repository.get_daily_report_payload(report_date)
    if daily_report_json is None:
        daily_report_json = build_empty_daily_payload(report_date)
    return build_daily_payload(daily_report_json)

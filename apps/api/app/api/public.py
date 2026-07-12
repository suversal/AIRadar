from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.services.taxonomy import display_category
from app.services.topics import item_matches_topic, topic_by_id

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


def _item_matches(
    item: dict[str, Any],
    *,
    category: str | None,
    q: str | None,
    topic: str | None = None,
) -> bool:
    if category:
        item_category = str(item.get("category") or "")
        # compare in display-taxonomy space so both scoring keys (older
        # payloads) and display keys match the same filter
        if item_category != category and display_category(item_category) != display_category(
            category
        ):
            return False
    if topic and not item_matches_topic(item, topic_by_id(topic)):
        return False
    if q:
        needles = [part for part in q.lower().split() if part]
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
        if any(needle not in haystack for needle in needles):
            return False
    return True


def _published_sort_key(item: dict[str, Any]) -> str:
    return str(item.get("published_at") or "")


def build_events_payload(
    daily_payloads: list[dict[str, Any]],
    *,
    category: str | None = None,
    q: str | None = None,
    topic: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    items, report_dates, updated_at = _merge_daily_items(daily_payloads)
    filtered = [
        item for item in items if _item_matches(item, category=category, q=q, topic=topic)
    ]
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
    topic: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    filtered = [
        item for item in items if _item_matches(item, category=category, q=q, topic=topic)
    ]
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


def _hotspot_seen_at(item: dict[str, Any]) -> datetime | None:
    # "48h 内被报道过" anchors on the event's latest coverage, so an older
    # event that just gained a new source still qualifies
    for key in ("last_seen_at", "published_at"):
        raw = item.get(key)
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def build_hotspots_payload(
    items: list[dict[str, Any]],
    *,
    category: str | None = None,
    q: str | None = None,
    hours: int = 48,
    limit: int = 5,
    now: datetime | None = None,
) -> dict[str, Any]:
    """多信源优先热点榜:窗口内 source_count >= 2 的事件按 (信源数, 评分)
    降序排在前,剩余名额用其余事件按评分补足。"""
    anchor = now or datetime.now(timezone.utc)
    window_start = anchor - timedelta(hours=hours)
    eligible: list[dict[str, Any]] = []
    for item in items:
        if item.get("hidden"):
            continue
        if not _item_matches(item, category=category, q=q):
            continue
        seen_at = _hotspot_seen_at(item)
        if seen_at is None or seen_at < window_start:
            continue
        eligible.append(item)

    def _score(item: dict[str, Any]) -> float:
        try:
            return float(item.get("final_score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _sources(item: dict[str, Any]) -> int:
        try:
            return max(int(item.get("source_count") or 1), 1)
        except (TypeError, ValueError):
            return 1

    multi = sorted(
        (item for item in eligible if _sources(item) >= 2),
        key=lambda item: (-_sources(item), -_score(item)),
    )
    rest = sorted(
        (item for item in eligible if _sources(item) < 2),
        key=lambda item: -_score(item),
    )
    board = (multi + rest)[:limit]
    return {
        "window_hours": hours,
        "item_count": len(board),
        "items": board,
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


def build_latest_selected_payload_from_repository(
    repository: Any,
    *,
    end_date: date,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    start_date = end_date - timedelta(days=6)
    items = repository.get_all_event_items_between(
        start_date,
        end_date,
        selected_only=True,
    )
    items = sorted(
        items,
        key=lambda item: (
            item.get("published_at") or "",
            float(item.get("final_score") or 0),
            int(item.get("source_count") or 1),
        ),
        reverse=True,
    )
    page = items[offset : offset + limit]
    return {
        "report_date": end_date.isoformat(),
        "updated_at": page[0].get("published_at") if page else None,
        "article_count": len(page),
        "total": len(items),
        "limit": limit,
        "offset": offset,
        "items": page,
    }


def build_daily_payload_from_repository(repository: Any, report_date: date) -> dict[str, Any]:
    daily_report_json = repository.get_daily_report_payload(report_date)
    if daily_report_json is None:
        daily_report_json = build_empty_daily_payload(report_date)
    return build_daily_payload(daily_report_json)

from __future__ import annotations

from datetime import date
from typing import Any


def build_empty_daily_payload(report_date: date | None = None) -> dict[str, Any]:
    resolved_date = report_date or date.today()
    return {
        "report_date": resolved_date.isoformat(),
        "title": "Suversal AI Radar 日报",
        "summary": "No report generated yet.",
        "updated_at": None,
        "sections": {},
        "items": [],
        "article_count": 0,
    }


def build_latest_payload(daily_report_json: dict[str, Any]) -> dict[str, Any]:
    return {
        "updated_at": daily_report_json.get("updated_at"),
        "items": daily_report_json.get("items", []),
    }


def build_daily_payload(daily_report_json: dict[str, Any]) -> dict[str, Any]:
    return {
        "report_date": daily_report_json["report_date"],
        "title": daily_report_json["title"],
        "summary": daily_report_json["summary"],
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

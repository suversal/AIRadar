from __future__ import annotations

from typing import Any


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


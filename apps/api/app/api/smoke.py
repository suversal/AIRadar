from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class APISmokeResult:
    name: str
    ok: bool
    detail: str


FetchJson = Callable[[str], dict[str, Any]]


def fetch_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def run_api_smoke_checks(
    base_url: str,
    *,
    report_date: str,
    fetch_json: FetchJson = fetch_json,
) -> list[APISmokeResult]:
    normalized_base_url = base_url.rstrip("/")
    checks = [
        (
            "health",
            f"{normalized_base_url}/health",
            _validate_health,
        ),
        (
            "latest",
            f"{normalized_base_url}/api/public/latest",
            _validate_latest,
        ),
        (
            "daily",
            f"{normalized_base_url}/api/public/daily/{report_date}",
            lambda payload: _validate_daily(payload, report_date),
        ),
    ]
    results = []
    for name, url, validator in checks:
        try:
            payload = fetch_json(url)
        except Exception as exc:
            results.append(APISmokeResult(name=name, ok=False, detail=str(exc)))
            continue
        ok, detail = validator(payload)
        results.append(APISmokeResult(name=name, ok=ok, detail=detail))
    return results


def format_api_smoke_results(results: list[APISmokeResult]) -> str:
    lines = []
    for result in results:
        status = "OK" if result.ok else "FAIL"
        lines.append(f"[{status}] {result.name}: {result.detail}")
    return "\n".join(lines)


def all_api_smoke_checks_passed(results: list[APISmokeResult]) -> bool:
    return all(result.ok for result in results)


def _validate_health(payload: dict[str, Any]) -> tuple[bool, str]:
    if payload.get("status") == "ok":
        return True, "status ok"
    return False, f"expected status ok (got {payload.get('status')!r})"


def _validate_latest(payload: dict[str, Any]) -> tuple[bool, str]:
    items = payload.get("items")
    if not isinstance(items, list):
        return False, "items is not a list"
    if not items:
        return False, "no items returned"
    return True, f"{len(items)} latest items"


def _validate_daily(payload: dict[str, Any], report_date: str) -> tuple[bool, str]:
    if payload.get("report_date") != report_date:
        return False, f"expected report_date {report_date} (got {payload.get('report_date')!r})"
    items = payload.get("items")
    if not isinstance(items, list):
        return False, "items is not a list"
    return True, f"{payload.get('article_count', len(items))} daily items"

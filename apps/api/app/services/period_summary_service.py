"""Period (weekly/monthly) report building with AI mainline summaries.

A period report is the aggregation of the interval's daily reports plus an
AI-written mainline: what the interval was really about. Pure aggregation
without the mainline is just a longer daily report, so the summary is the
point of this module; provider failures degrade to a deterministic
fallback instead of blocking report generation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.api.public import month_range, sort_period_items

logger = logging.getLogger(__name__)

SUMMARY_ITEM_LIMIT = 40

#: Minimum body length before a draft is retried once.
#:
#: The prompt asks for 360-440 characters; measured output across every
#: generated period report was 139-188. The prompt could only ask, and nothing
#: checked, so each thin draft was published as written.
#:
#: This floor sits deliberately *below* what the prompt asks. Its job is to
#: catch a draft too thin to be a summary at all - not to enforce the target.
#: A short but real summary still beats the deterministic fallback
#: (「本期 AI 综述生成失败」), so rejecting on length alone would make the page
#: worse rather than better; see build_period_report, which publishes the second
#: attempt whatever its length.
MAINLINE_BODY_MIN_CHARS = 200

SUMMARY_ATTEMPTS = 2

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


def period_targets_for(kind: str, anchor_date: date) -> list[str]:
    """Which period keys a refresh anchored on this date must consider:
    the period the date falls in, plus the one just before it.

    The previous period is what makes finalization actually happen. Its
    last in-period refresh runs before its final day is fully settled
    (late-evening runs can still amend that day's daily report), so the
    closing pass has to come from the *next* period's refreshes - the first
    run after rollover rebuilds the previous period from its days' settled
    state and freezes it. Once frozen, later runs skip it on finalized_at,
    so this costs one extra AI call per rollover, not one per run."""
    current = period_key_for(kind, anchor_date)
    current_start, _ = period_range_for_key(kind, current)
    previous = period_key_for(kind, current_start - timedelta(days=1))
    # previous first: give the closing pass its freeze before spending
    # anything on the still-moving current period
    return [previous, current]


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
    ranked = sort_period_items(items)
    return [
        {
            "title": str(item.get("title") or "")[:80],
            "summary": str(item.get("one_line_summary") or item.get("summary") or "")[:120],
            "category": str(item.get("focus_category") or item.get("category") or ""),
        }
        for item in ranked[:SUMMARY_ITEM_LIMIT]
    ]


def summary_digest(summary_input: list[dict[str, Any]]) -> str:
    """Fingerprint of the material the AI is shown. Equal digest -> the call
    would see the same input, so the stored text is reused instead of paid
    for again. Same contract as daily_summary_service.summary_digest."""
    canonical = json.dumps(summary_input, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _fallback_summary(kind: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    label = "本周" if kind == "weekly" else "本月"
    top = sort_period_items(items)
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
    ranked = sort_period_items(items)
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
        label = str(
            item.get("focus_category_label")
            or item.get("category_label")
            or item.get("focus_category")
            or item.get("category")
            or "其他"
        )
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
    previous: dict[str, Any] | None = None,
    finalize: bool = False,
) -> dict[str, Any]:
    """Build the period's snapshot, buying new AI text only when needed.

    previous is the stored report (if any). The entries/stats snapshot is
    always rebuilt - it is a free database write and must track the newest
    daily state - but the AI text is reused from previous when the summary
    input's fingerprint is unchanged. This is what decouples "the page's
    masthead is fresh" from "the prose was re-bought": before the digest,
    summarize_period ran 23 times on 2026-08-18 against summarize_daily's 6.

    finalize=True marks the report frozen (finalized_at) - but only when the
    summary actually generated. Freezing a fallback row would make 「生成失败」
    the period's permanent text; leaving it unfrozen lets the next rollover
    run retry.
    """
    key = period_key_for(kind, anchor)
    range_start, range_end = period_range_for_key(kind, key)
    range_label = f"{range_start.isoformat()} ~ {range_end.isoformat()}"

    summary_input = _summary_input(items)
    digest = summary_digest(summary_input)

    status = "generated"
    summary: dict[str, Any] | None = None
    if (
        previous
        and previous.get("status") == "generated"
        and previous.get("summary_digest") == digest
    ):
        # unchanged input, healthy stored text: reuse it. A fallback row never
        # gets here (its digest is stored as None), so failures always retry.
        summary = {
            "mainline_title": previous.get("mainline_title") or "",
            "mainline_body": previous.get("mainline_body") or "",
            "theme_notes": list(previous.get("theme_notes") or []),
        }
    else:
        for attempt in range(1, SUMMARY_ATTEMPTS + 1):
            try:
                drafted = ai_provider.summarize_period(summary_input, kind, range_label)
                drafted = parse_period_summary_payload(drafted)
            except Exception:
                logger.warning(
                    "period summary attempt %d/%d failed for %s %s",
                    attempt,
                    SUMMARY_ATTEMPTS,
                    kind,
                    key,
                    exc_info=True,
                )
                continue
            # keep the newest draft either way: a short summary is still worth
            # publishing, so length only decides whether to spend another attempt
            summary = drafted
            if len(drafted["mainline_body"]) >= MAINLINE_BODY_MIN_CHARS:
                break
            logger.warning(
                "period summary for %s %s is %d chars (min %d) on attempt %d/%d",
                kind,
                key,
                len(drafted["mainline_body"]),
                MAINLINE_BODY_MIN_CHARS,
                attempt,
                SUMMARY_ATTEMPTS,
            )
        if summary is None:
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
        # digest only on generated: a fallback must not block the next retry
        "summary_digest": digest if status == "generated" else None,
        "finalized_at": (
            datetime.now(timezone.utc).isoformat()
            if finalize and status == "generated"
            else None
        ),
    }

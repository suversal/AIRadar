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


#: 周报名单上限与分类保底、月报名单上限。2026-08-19 拍板的数字，不是算出来
#: 的——先按这个跑两期看实际效果再调。
WEEKLY_ITEM_CAP = 40
WEEKLY_CATEGORY_FLOOR = 2
MONTHLY_ITEM_CAP = 25

#: 月报门槛（多信源或多天出现）筛完不足这个数时按名次回填。月初头几天
#: 几乎不会有 days_covered≥2 的事件，不回填的话当期月报页面就是空的。
MONTHLY_FILL_FLOOR = 10


def _is_multi_source(item: dict[str, Any]) -> bool:
    try:
        return int(item.get("source_count") or 1) > 1
    except (TypeError, ValueError):
        return False


def _days_covered(item: dict[str, Any]) -> int:
    try:
        return max(int(item.get("days_covered") or 1), 1)
    except (TypeError, ValueError):
        return 1


def _item_category(item: dict[str, Any]) -> str:
    return str(item.get("focus_category") or item.get("category") or "")


def select_period_items(kind: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从期间全量条目里定周/月报的入选名单——报告不再是「全收录但 96% 不可
    见」，而是一份明确的名单；没入选的仍在 /all 可查。

    选择只依赖两个客观计数（source_count、days_covered）加组内分位名次，
    刻意不比较绝对分——绝对分只在同一个打分模型内可比，日报敢用 60 分硬线
    是因为一天之内只有一个模型（见 scoring_service），周月报跨天跨模型，
    必须用名次逻辑（见 sort_period_items 的换模型事故）。
    """
    if kind == "weekly":
        return _select_weekly_items(items)
    if kind == "monthly":
        return _select_monthly_items(items)
    raise ValueError(f"unknown period kind: {kind}")


def _select_weekly_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """周报宽进：多信源全收 + 每分类保底 + 全局分位补足到上限。

    「被多家报道」是是非题，多信源事件全量入选、不占任何名额。分类保底
    让每个当周有内容的分类至少有 WEEKLY_CATEGORY_FLOOR 条露出——周报页面
    按分类分板块渲染，选品口径必须和渲染结构对齐，否则产出量小的分类会
    被产出量大的分类按全局名次挤到整块消失。
    """
    ranked = sort_period_items(items)
    position = {id(item): index for index, item in enumerate(ranked)}

    def group_key(item: dict[str, Any]) -> tuple[int, int]:
        # 组内先比持续度再比分位名次：连报三天的事排在昙花一现的前面
        return (-_days_covered(item), position[id(item)])

    multi = sorted((item for item in ranked if _is_multi_source(item)), key=group_key)
    single = sorted((item for item in ranked if not _is_multi_source(item)), key=group_key)

    selected = multi[:WEEKLY_ITEM_CAP]
    chosen = {id(item) for item in selected}

    # 分类保底：目标是每个分类在名单里至少 FLOOR 条（多信源占位也算数——
    # 一个已有 3 条多信源大事的分类不需要再靠保底撑存在感）
    if len(selected) < WEEKLY_ITEM_CAP:
        represented: dict[str, int] = {}
        for item in selected:
            key = _item_category(item)
            represented[key] = represented.get(key, 0) + 1
        floor_picks: list[dict[str, Any]] = []
        for item in single:
            key = _item_category(item)
            if represented.get(key, 0) < WEEKLY_CATEGORY_FLOOR:
                floor_picks.append(item)
                represented[key] = represented.get(key, 0) + 1
        for item in floor_picks:
            if len(selected) >= WEEKLY_ITEM_CAP:
                break
            selected.append(item)
            chosen.add(id(item))

    # 全局补足：剩余名额按同一把组内键从单信源里取
    for item in single:
        if len(selected) >= WEEKLY_ITEM_CAP:
            break
        if id(item) not in chosen:
            selected.append(item)
            chosen.add(id(item))

    # 名单顺序 = 页面顺序：多信源组整体在前，单信源部分重排回组内键序
    # （保底条目是按分类挑出来的，直接 append 会把顺序搅乱）
    selected_single = sorted(
        (item for item in selected if not _is_multi_source(item)), key=group_key
    )
    return [item for item in selected if _is_multi_source(item)] + selected_single


def _select_monthly_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """月报严进：多信源**或**进过至少两天日报的事件才有资格，再按
    （多信源 → 持续度 → 分位名次）取前 MONTHLY_ITEM_CAP 条。

    单信源且只出现一天的事，月尺度上不构成「值得回顾」的证据——这个门槛
    同时天然屏蔽了换模型的分数噪声：月报选品几乎不依赖绝对分。不做分类
    保底：月报正文按趋势组织，不按分类分板块，没有对齐需求。
    """
    ranked = sort_period_items(items)
    position = {id(item): index for index, item in enumerate(ranked)}

    def rank_key(item: dict[str, Any]) -> tuple[bool, int, int]:
        return (not _is_multi_source(item), -_days_covered(item), position[id(item)])

    eligible = sorted(
        (
            item
            for item in ranked
            if _is_multi_source(item) or _days_covered(item) >= 2
        ),
        key=rank_key,
    )
    selected = eligible[:MONTHLY_ITEM_CAP]
    if len(selected) < MONTHLY_FILL_FLOOR:
        chosen = {id(item) for item in selected}
        for item in ranked:
            if len(selected) >= MONTHLY_FILL_FLOOR:
                break
            if id(item) not in chosen:
                selected.append(item)
    return selected


def _summary_input(selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the AI is shown: exactly the selection, in selection order. The
    prose must be written from what the reader will actually see - same
    contract as _regenerate_daily_summary reading the resolved payload.
    SUMMARY_ITEM_LIMIT stays as a fuse only; both caps sit at or below it."""
    return [
        {
            "title": str(item.get("title") or "")[:80],
            "summary": str(item.get("one_line_summary") or item.get("summary") or "")[:120],
            "category": str(item.get("focus_category") or item.get("category") or ""),
            "source_count": int(item.get("source_count") or 1),
            "days_covered": _days_covered(item),
        }
        for item in selected[:SUMMARY_ITEM_LIMIT]
    ]


def summary_digest(summary_input: list[dict[str, Any]]) -> str:
    """Fingerprint of the material the AI is shown. Equal digest -> the call
    would see the same input, so the stored text is reused instead of paid
    for again. Same contract as daily_summary_service.summary_digest."""
    canonical = json.dumps(summary_input, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _fallback_summary(kind: str, selected: list[dict[str, Any]]) -> dict[str, Any]:
    label = "本周" if kind == "weekly" else "本月"
    top_title = str(selected[0].get("title")) if selected else "AI 动态"
    return {
        "mainline_title": f"{label} AI 动态一览",
        "mainline_body": (
            f"{label}共收录 {len(selected)} 条 AI 动态，代表事件包括「{top_title}」等。"
            "本期 AI 综述生成失败，以上为自动概要；下次日报刷新时将重试。"
        ),
        "theme_notes": [],
    }


def _entries_snapshot(selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Freeze which events were selected, in what order, and their score at
    generation time. Content (title/summary/reason/tags/...) is deliberately
    excluded - it is always resolved live from event_id at read time, same
    as daily_report_entries. days_covered is the exception: it is a rollup
    artifact (how many dailies carried the event), not resolvable from the
    event itself, so it must be frozen here or lost."""
    return [
        {
            "event_id": item.get("event_id"),
            "score_at_selection": float(item.get("final_score") or 0.0),
            "days_covered": _days_covered(item),
        }
        for item in selected
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


def _period_stats(
    items: list[dict[str, Any]], selected: list[dict[str, Any]]
) -> dict[str, Any]:
    """诚实的双口径：覆盖面统计（source 覆盖、多信源比例、分类分布）看的
    是期间**全量**，入选/覆盖两个计数分开存——页面不再拿名单长度冒充
    「收录动态 658」。"""
    stats = _stats_snapshot(items)
    stats["selected_count"] = len(selected)
    stats["coverage_count"] = len(items)
    return stats


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

    # 名单在这里一次定死：页面（经 entries 快照）和 AI 综述（经
    # summary_input）看到的是同一份、同一个顺序的东西
    selected = select_period_items(kind, items)
    summary_input = _summary_input(selected)
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
            summary = _fallback_summary(kind, selected)
            status = "fallback"

    return {
        "kind": kind,
        "period_key": key,
        "range_start": range_start.isoformat(),
        "range_end": range_end.isoformat(),
        "mainline_title": summary["mainline_title"],
        "mainline_body": summary["mainline_body"],
        "theme_notes": summary["theme_notes"],
        # article_count 是名单数，不是覆盖数——归档侧栏的「N 条动态」和
        # 页面的条目数从此说的是同一个数字；覆盖数在 stats.coverage_count
        "article_count": len(selected),
        "report_dates": list(report_dates),
        "entries": _entries_snapshot(selected),
        "stats": _period_stats(items, selected),
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

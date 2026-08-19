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
from app.services.taxonomy import FOCUS_CATEGORIES, resolve_focus_category

logger = logging.getLogger(__name__)

_FOCUS_LABELS = dict(FOCUS_CATEGORIES)

#: 喂给 AI 的条目上限。80 而不是 40：周报名单在多信源多的一周会超过
#: WEEKLY_ITEM_CAP（多信源全收优先于 cap），40 会把名单尾部挡在综述之外，
#: 违背「AI 输入 = 入选名单本身」。
SUMMARY_ITEM_LIMIT = 80

#: 输入 JSON 的字符预算。provider 侧对 user content 做定长截断，而截断一份
#: JSON 会从字符串中间切断、送出非法 JSON——所以规模控制放在这里按**整条**
#: 丢弃，保证发出去的永远是合法 JSON，provider 那道只当最后的保险丝。
#: 实测：月报 25 条 5.2k、周报 40 条 6.1k，预算留到 12k 是给长标题的余量。
SUMMARY_INPUT_CHAR_BUDGET = 12000

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

#: 月报主线是一段定调的总述（prompt 要求 150-250 字），不是周报那种 2-3 条
#: 主线的长文——正文主体在趋势线里。重试线相应放低。
MONTHLY_MAINLINE_MIN_CHARS = 100

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


def parse_period_summary_payload(payload: dict[str, Any], kind: str = "weekly") -> dict[str, Any]:
    """Normalize a weekly/monthly AI payload into the stored shape.

    Both kinds land in the same theme_notes column but carry different
    structures - weekly notes are per focus category (mirroring the daily
    report), monthly notes are free-form trends with supporting event ids:

    - weekly:  [{"category", "label", "note"}]
    - monthly: [{"label", "note", "event_ids"}]

    The parser is deliberately tolerant of both the raw AI keys
    (category_notes/trends/theme_notes) and its own normalized output, because
    providers parse internally and build_period_report parses again.
    """
    title = str(payload.get("mainline_title") or "").strip()
    body = str(payload.get("mainline_body") or "").strip()
    if not title or not body:
        raise ValueError("period summary payload missing mainline_title/mainline_body")

    theme_notes: list[dict[str, Any]] = []
    if kind == "weekly":
        for note in payload.get("category_notes") or payload.get("theme_notes") or []:
            if not isinstance(note, dict):
                continue
            key = str(note.get("category") or "").strip()
            text = str(note.get("note") or "").strip()
            if key in _FOCUS_LABELS and text:
                theme_notes.append(
                    {"category": key, "label": _FOCUS_LABELS[key], "note": text}
                )
    else:
        for note in payload.get("trends") or payload.get("theme_notes") or []:
            if not isinstance(note, dict):
                continue
            label = str(note.get("label") or "").strip()
            text = str(note.get("note") or "").strip()
            if not label or not text:
                continue
            event_ids = [
                str(event_id)
                for event_id in (note.get("event_ids") or [])
                if event_id
            ]
            theme_notes.append({"label": label, "note": text, "event_ids": event_ids})
    return {"mainline_title": title, "mainline_body": body, "theme_notes": theme_notes}


#: 周报名单上限与分类保底、月报名单上限。2026-08-19 拍板的数字，不是算出来
#: 的——先按这个跑两期看实际效果再调。
#:
#: WEEKLY_ITEM_CAP 是**单信源补足的目标规模**，不是名单硬上限：多信源全收
#: 与分类保底都优先于它，所以多信源多的一周名单会超过这个数。原先它是硬
#: 上限，`multi[:40]` 把多信源截断掉——2026-08-10 那周实测 48 条多信源，
#: 8 条被静默丢弃，而且名额被占满导致保底与补足整体跳过，纯单信源的分类
#: 整块从周报消失，正是保底要防的那件事。
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
    """分类保底数名额用的 key，必须和页面分板块、AI 分类输入用同一把解析
    （_group_selected_by_focus 与 slim_period_items 都走 resolve_focus_category）。
    原来这里取的是未解析的原始字符串，于是 focus_category 为空、
    category="模型发布" 的条目被当成一个独立分类，白占一份保底名额，而真正
    欠保底的分类反而挤不进来。"""
    return str(
        resolve_focus_category(
            item.get("focus_category"),
            item.get("scoring_category") or item.get("category"),
        )
        or ""
    )


def select_period_items(kind: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从期间全量条目里定周/月报的入选名单——报告不再是「全收录但 96% 不可
    见」，而是一份明确的名单；没入选的仍在 /all 可查。

    选择只依赖两个客观计数（source_count、days_covered）加组内分位名次，
    刻意不比较绝对分——绝对分只在同一个打分模型内可比，日报敢用 60 分硬线
    是因为一天之内只有一个模型（见 scoring_service），周月报跨天跨模型，
    必须用名次逻辑（见 sort_period_items 的换模型事故）。
    """
    # 没有 event_id 的条目进不了名单：entries 快照按 event_id 冻结、页面按
    # event_id 现场解析，留着它们只会让 article_count 比页面真正渲染出来的
    # 条数多，而月报还会把它们喂进 AI（综述描写读者看不见的事件）。
    # _merge_daily_items 允许用 original_url/title 兜底做合并键，所以旧格式
    # 的日报条目确实可能走到这里。
    items = [item for item in items if item.get("event_id")]
    if kind == "weekly":
        return _select_weekly_items(items)
    if kind == "monthly":
        return _select_monthly_items(items)
    raise ValueError(f"unknown period kind: {kind}")


def _select_weekly_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """周报宽进：多信源全收 + 每分类保底 + 单信源按分位补足到目标规模。

    「被多家报道」是是非题，多信源事件全量入选、不占任何名额。分类保底
    让每个当周有内容的分类至少有 WEEKLY_CATEGORY_FLOOR 条露出——周报页面
    按分类分板块渲染，选品口径必须和渲染结构对齐，否则产出量小的分类会
    被产出量大的分类按全局名次挤到整块消失。

    这两件事都排在 WEEKLY_ITEM_CAP 之前：cap 只约束最后那步「按分位补
    单信源」。多信源多的一周（实测 48 条）名单因此会超过 cap，这是对的
    ——一周真有 48 件多家同时报道的事，就该 48 件都露出来。
    """
    ranked = sort_period_items(items)
    position = {id(item): index for index, item in enumerate(ranked)}

    def group_key(item: dict[str, Any]) -> tuple[int, int]:
        # 组内先比持续度再比分位名次：连报三天的事排在昙花一现的前面
        return (-_days_covered(item), position[id(item)])

    multi = sorted((item for item in ranked if _is_multi_source(item)), key=group_key)
    single = sorted((item for item in ranked if not _is_multi_source(item)), key=group_key)

    # 多信源全收，不截断：这是契约里最硬的一条
    selected = list(multi)
    chosen = {id(item) for item in selected}

    # 分类保底：每个分类在名单里至少 FLOOR 条（多信源占位也算数——一个已有
    # 3 条多信源大事的分类不需要再靠保底撑存在感）。同样不受 cap 约束，
    # 否则多信源占满名额时保底会整体失效，小分类照样消失。
    represented: dict[str, int] = {}
    for item in selected:
        key = _item_category(item)
        represented[key] = represented.get(key, 0) + 1
    for item in single:
        key = _item_category(item)
        if represented.get(key, 0) < WEEKLY_CATEGORY_FLOOR:
            selected.append(item)
            chosen.add(id(item))
            represented[key] = represented.get(key, 0) + 1

    # 补足：只有这一步看 cap，按同一把组内键从剩下的单信源里取
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


def _group_selected_by_focus(
    selected: list[dict[str, Any]],
) -> list[tuple[str, str, list[dict[str, Any]]]]:
    """(key, label, items) per focus category present in the selection, in
    FOCUS_CATEGORIES order, preserving selection order within each group -
    the AI's category input must mirror what the page's category sections
    will render, not a re-sort of it."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in selected:
        key = resolve_focus_category(
            item.get("focus_category"),
            item.get("scoring_category") or item.get("category"),
        )
        grouped.setdefault(str(key), []).append(item)
    return [
        (key, label, grouped[key])
        for key, label in FOCUS_CATEGORIES
        if grouped.get(key)
    ]


def _summary_input(kind: str, selected: list[dict[str, Any]]) -> dict[str, Any]:
    """What the AI is shown: exactly the selection, in selection order. The
    prose must be written from what the reader will actually see - same
    contract as _regenerate_daily_summary reading the resolved payload.

    Weekly mirrors the daily report's two-scope structure (mainline from the
    multi-source events, one note per category from that category's whole
    selection). Monthly is a flat event list with ids - the AI groups it into
    trends itself and must quote event_ids as evidence.

    Trimmed to SUMMARY_ITEM_LIMIT items, then whole items are dropped from the
    tail until the serialized payload fits SUMMARY_INPUT_CHAR_BUDGET - dropping
    by item keeps the JSON valid, which a character-level cut downstream would
    not. Both are fuses: a normal week or month sits well inside them."""
    selected = selected[:SUMMARY_ITEM_LIMIT]
    while True:
        built = _build_summary_input(kind, selected)
        if len(selected) <= 1 or len(
            json.dumps(built, ensure_ascii=False)
        ) <= SUMMARY_INPUT_CHAR_BUDGET:
            return built
        logger.warning(
            "%s summary input over budget with %d items, dropping the tail one",
            kind,
            len(selected),
        )
        selected = selected[:-1]


def _build_summary_input(kind: str, selected: list[dict[str, Any]]) -> dict[str, Any]:
    if kind == "weekly":
        return {
            "mainline_events": [
                {
                    "title": str(item.get("title") or "")[:70],
                    "summary": str(item.get("one_line_summary") or item.get("summary") or "")[:110],
                    "category": str(item.get("focus_category") or item.get("category") or ""),
                    "source_count": int(item.get("source_count") or 1),
                    "days_covered": _days_covered(item),
                }
                for item in selected
                if _is_multi_source(item)
            ],
            "categories": [
                {
                    "category": key,
                    "label": label,
                    "item_count": len(group),
                    "titles": [str(item.get("title") or "")[:60] for item in group],
                }
                for key, label, group in _group_selected_by_focus(selected)
            ],
        }
    return {
        "events": [
            {
                "event_id": str(item.get("event_id") or ""),
                "title": str(item.get("title") or "")[:80],
                "summary": str(item.get("one_line_summary") or item.get("summary") or "")[:120],
                "category": str(item.get("focus_category") or item.get("category") or ""),
                "source_count": int(item.get("source_count") or 1),
                "days_covered": _days_covered(item),
            }
            for item in selected
        ]
    }


def summary_digest(summary_input: list[dict[str, Any]]) -> str:
    """Fingerprint of the material the AI is shown. Equal digest -> the call
    would see the same input, so the stored text is reused instead of paid
    for again. Same contract as daily_summary_service.summary_digest.

    进行中的期次会比日报重买得勤：它的底盘含「今天」那份还在滚动修订的
    日报，今天多挂一篇文章让某条的 source_count 从 3 变 4，周月两份指纹
    就一起失效。这是刻意留的——source_count 与名次顺序都是综述的实质
    输入，把它们排除在指纹外能省几次调用，但会让文字和页面上的数字对不
    上，那是比多花几毛钱更糟的退化。指纹要挡的是「素材根本没动」的空转
    趟，不是「变化不大」的趟。"""
    canonical = json.dumps(summary_input, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _has_report_body(summary: dict[str, Any], selected: list[dict[str, Any]]) -> bool:
    """正文主体到底写出来没有。

    月报的趋势线、周报的分类概述都存在 theme_notes 里，而它们**就是**报告
    的正文主体：月报少了趋势只剩一段总述加榜单，周报少了概述会退化成拿
    头条标题冒充概述。解析侧对这两者是静默容忍的（AI 把 trends 回成一个
    字符串而不是对象数组时全部被丢弃），所以只量 mainline_body 长度的闸门
    放得过去——一份没有正文的报告会以 generated 入库，跨期时还会被封版
    冻成永久状态。名单为空时另说：那本来就没有正文可写。"""
    if not selected:
        return True
    return bool(summary.get("theme_notes"))


def _validated_trend_notes(
    theme_notes: list[dict[str, Any]], selected: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """月报趋势线的证据校验：回填的 event_id 必须真在入选名单里，回填错的
    直接丢弃。一条趋势一个合法 id 都没有时保留论述、挂空证据列表——页面
    只显示文字不挂卡片。刻意**不做**「兜底塞几条高分事件冒充证据」：宁缺
    毋假。"""
    allowed = {
        str(item.get("event_id"))
        for item in selected
        if item.get("event_id")
    }
    validated = []
    for note in theme_notes:
        event_ids = [
            event_id for event_id in note.get("event_ids") or [] if event_id in allowed
        ]
        validated.append({**note, "event_ids": event_ids})
    return validated


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


def _empty_period_report(
    *,
    kind: str,
    key: str,
    range_start: date,
    range_end: date,
    items: list[dict[str, Any]],
    report_dates: list[str],
) -> dict[str, Any]:
    """名单为空时的报告行：不编造综述，前端按 status 显示空状态。"""
    return {
        "kind": kind,
        "period_key": key,
        "range_start": range_start.isoformat(),
        "range_end": range_end.isoformat(),
        "mainline_title": "",
        "mainline_body": "",
        "theme_notes": [],
        "article_count": 0,
        "report_dates": list(report_dates),
        "entries": [],
        "stats": _period_stats(items, []),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "empty",
        "summary_digest": None,
        "finalized_at": None,
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

    # 名单在这里一次定死：页面（经 entries 快照）和 AI 综述（经
    # summary_input）看到的是同一份、同一个顺序的东西
    selected = select_period_items(kind, items)
    summary_input = _summary_input(kind, selected)
    digest = summary_digest(summary_input)
    mainline_min_chars = (
        MAINLINE_BODY_MIN_CHARS if kind == "weekly" else MONTHLY_MAINLINE_MIN_CHARS
    )

    if not selected:
        # 名单空了（期内条目全被审核移除是真会发生的）。日报侧对空输入有守卫，
        # 这边原来没有：拿一份空 summary_input 去调 AI，只校验 title/body 非空
        # 的解析会把凭空编出来的一段文字当成综述存下，跨期时还封版冻住。
        # 不调用、不封版、不存指纹——什么时候有内容了，什么时候再写。
        logger.warning("period %s %s has no selectable items; skipping the AI call", kind, key)
        return _empty_period_report(
            kind=kind,
            key=key,
            range_start=range_start,
            range_end=range_end,
            items=items,
            report_dates=report_dates,
        )

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
                drafted = parse_period_summary_payload(drafted, kind)
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
            if kind == "monthly":
                drafted["theme_notes"] = _validated_trend_notes(
                    drafted["theme_notes"], selected
                )
            # keep the newest draft either way: a short summary is still worth
            # publishing, so quality only decides whether to spend another attempt
            summary = drafted
            long_enough = len(drafted["mainline_body"]) >= mainline_min_chars
            has_body = _has_report_body(drafted, selected)
            if long_enough and has_body:
                break
            if not long_enough:
                logger.warning(
                    "period summary for %s %s is %d chars (min %d) on attempt %d/%d",
                    kind,
                    key,
                    len(drafted["mainline_body"]),
                    mainline_min_chars,
                    attempt,
                    SUMMARY_ATTEMPTS,
                )
            if not has_body:
                logger.warning(
                    "period summary for %s %s came back with no %s on attempt %d/%d",
                    kind,
                    key,
                    "trends" if kind == "monthly" else "category notes",
                    attempt,
                    SUMMARY_ATTEMPTS,
                )
        if summary is None:
            # 失败了。已有一份写成过的正文时保留它，只让快照跟上新素材——
            # 拿「本期 AI 综述生成失败」覆盖一段真写出来的综述，是把一次
            # 临时的 provider 故障变成读者可见的内容退化。存量是 fallback
            # 或从来没写出过，才用兜底文案占位。
            if previous and previous.get("status") == "generated" and previous.get(
                "mainline_body"
            ):
                summary = {
                    "mainline_title": previous.get("mainline_title") or "",
                    "mainline_body": previous.get("mainline_body") or "",
                    "theme_notes": list(previous.get("theme_notes") or []),
                }
                # 文字是旧的、素材是新的：不存指纹，下一轮必然重试，把这段
                # 旧文字换成对得上新名单的版本
                status = "stale"
                logger.warning(
                    "period summary for %s %s kept the stored text after %d failed attempts",
                    kind,
                    key,
                    SUMMARY_ATTEMPTS,
                )
            else:
                summary = _fallback_summary(kind, selected)
                status = "fallback"
        elif not _has_report_body(summary, selected):
            # 总述写出来了但正文主体（月报趋势/周报分类概述）是空的：发布它
            # 总比空白强，但不能当成写完了——不存指纹、不封版，下一轮重试。
            # 否则一次跑偏的输出会被冻成这个期次的永久形态。
            status = "partial"

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
        # 指纹与封版都只给 generated。其余三种状态各有各的不完整——fallback
        # 从没写成过、stale 是留着的旧文、partial 缺正文主体——都必须留着被
        # 下一轮重试的机会，存指纹会让它们被判重挡住，封版会把它们冻成永久。
        "summary_digest": digest if status == "generated" else None,
        "finalized_at": (
            datetime.now(timezone.utc).isoformat()
            if finalize and status == "generated"
            else None
        ),
    }

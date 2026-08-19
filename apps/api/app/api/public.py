from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.services.taxonomy import (
    display_category,
    resolve_focus_category,
    source_filter_bucket,
)
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
    # 这件事进过几天的日报。合并去重原本把这个信息直接丢掉了，但它是
    # 周月报独有的重要性信号：连报三天的事天然是本期主线候选。和
    # source_count 一样是客观计数，不受换打分模型影响。
    covered_days: dict[str, set[str]] = {}
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
            covered_days.setdefault(str(event_id), set()).add(str(report_date or ""))
    items = [
        # copy before annotating: the stored daily payload dicts are not ours to mutate
        {**item, "days_covered": len(covered_days[key])}
        for key, item in merged.items()
    ]
    return items, report_dates, updated_at


def _item_matches(
    item: dict[str, Any],
    *,
    category: str | None,
    q: str | None,
    topic: str | None = None,
    focus: str | None = None,
    source: str | None = None,
    tag: str | None = None,
) -> bool:
    if source:
        item_source_category = (item.get("main_source") or {}).get("category")
        if source_filter_bucket(item_source_category) != source:
            return False
    if focus:
        item_text = " ".join(
            [
                str(item.get("title") or ""),
                str(item.get("one_line_summary") or ""),
                str(item.get("summary") or ""),
                " ".join(str(tag) for tag in item.get("tags") or []),
            ]
        )
        item_focus = resolve_focus_category(
            item.get("focus_category"),
            item.get("scoring_category") or item.get("category"),
            text=item_text,
        )
        requested_focus = resolve_focus_category(focus, focus)
        if item_focus != requested_focus:
            return False
    if category:
        item_category = str(item.get("category") or "")
        if item_category != category and display_category(item_category) != display_category(
            category
        ):
            return False
    if tag:
        requested_tag = tag.strip().casefold()
        item_tags = {
            str(item_tag).strip().casefold()
            for item_tag in item.get("tags") or []
            if str(item_tag).strip()
        }
        if requested_tag not in item_tags:
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


def build_events_payload_from_items(
    items: list[dict[str, Any]],
    *,
    category: str | None = None,
    focus: str | None = None,
    source: str | None = None,
    tag: str | None = None,
    q: str | None = None,
    topic: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    filtered = [
        item
        for item in items
        if _item_matches(
            item,
            category=category,
            focus=focus,
            source=source,
            tag=tag,
            q=q,
            topic=topic,
        )
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
    focus: str | None = None,
    tag: str | None = None,
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
        # 2026-07-13:/all 和后台不再去重，同一事件的每个成员各自成条；
        # 热点榜必须只把事件的代表条(is_main)当候选，否则一个多信源
        # 事件会用它的全部成员挤满榜单——source_count 已经是聚合值了
        if not item.get("is_main", True):
            continue
        if not _item_matches(item, category=category, focus=focus, tag=tag, q=q):
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


def _final_score(item: dict[str, Any]) -> float:
    try:
        return float(item.get("final_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def sort_period_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """周月报的排序：先按打分模型分组，组内排名，再按组内分位合并。

    final_score 只在同一个模型内部可比。2026-08-13 从 DeepSeek 换到 Qwen 之后
    高分明显变稀：Qwen 期 166 条里 89.1 以上只有 2 条，DeepSeek 期 489 条里有
    20 条。按原始分全期排序的结果是 2026-08 月报 top20 里 08-15 及之后的内容
    **一条都没有**，「英伟达 5000 亿算力平台」「SpaceX 收购 Cursor」这种当月
    大事被一个与新闻本身无关的原因排除了。

    注意两个模型的分数区间是重叠的（Qwen 接手当天下午就打出过 96.0 和
    100.0），差的是分布而不是硬上限——所以卡一条绝对分的线修不好这件事，
    只能不比绝对分，改比「在自己那一代评分里排第几」：每组内部按分数排名，
    取分位 rank/len(group) 作为跨组可比的键。两条性质是刻意的：

    - 只有一个模型时（绝大多数周报、以及换模型之前的全部历史），组内名次
      与分数降序完全一致，行为和改之前一模一样，不会平白扰动已有报表。
    - 组越大，它的头名分位越靠前（1/489 < 1/166）。一个只有几条的组不会
      靠「我组内第一」挤到月报榜首——样本太少本来就不构成重要性证据。

    model_used 为空的历史条目自成一组，同样按上面的规则参与排序。
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        groups.setdefault(str(item.get("model_used") or ""), []).append(item)

    keyed: list[tuple[float, float, str, dict[str, Any]]] = []
    for group in groups.values():
        group.sort(key=lambda item: -_final_score(item))
        size = len(group)
        for rank, item in enumerate(group, start=1):
            # 同分位时用原始分兜底只是为了排序稳定，不代表跨模型的分数可比
            keyed.append((rank / size, -_final_score(item), str(item.get("event_id") or ""), item))
    keyed.sort(key=lambda entry: entry[:3])
    return [entry[3] for entry in keyed]


def build_period_payload(
    daily_payloads: list[dict[str, Any]],
    *,
    mode: str,
    range_start: date,
    range_end: date,
) -> dict[str, Any]:
    items, report_dates, updated_at = _merge_daily_items(daily_payloads)
    items = sort_period_items(items)
    return {
        "mode": mode,
        "range_start": range_start.isoformat(),
        "range_end": range_end.isoformat(),
        "report_dates": report_dates,
        "updated_at": updated_at,
        "article_count": len(items),
        "items": items,
    }


#: 周报/月报的对外负载里要剥掉的字段。
#:
#: 这些是文章正文本身。周月报页面一个都不用——它只渲染标题、推荐理由、
#: 标签、来源数，而且每个板块只展示前 3 条（见 apps/web/app/reports/
#: period-report-page.tsx）。但接口一直在把范围内**每一篇**文章的完整正文
#: 都发出去：实测一份月报 476 条、16.4 MB，其中这几个字段占 96%。
#:
#: 是 2026-08-13 加缓存时被 Next 的构建日志暴露出来的——
#: "items over 2MB can not be cached"，才发现这个负载有多大。
#: 剥掉之后 items 从 11.6 MB 降到约 0.5 MB。
#:
#: 用"剥掉哪些"而不是"保留哪些"，是为了不误伤：将来给事件加了新字段，
#: 页面能直接用上，不会因为忘了加进白名单而神秘地读不到值。
PERIOD_ITEM_HEAVY_FIELDS = (
    "original_blocks",
    "original_content",
    "original_images",
    "original_markdown",
    "original_paragraphs",
    "translated_blocks",
    "translated_content",
    "translated_paragraphs",
)


def slim_period_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把周月报条目里的文章正文剥掉，只留列表展示需要的部分，并把 focus
    分类解析成最终值再发出去。

    正文：只用在**对外读取**这条路径上。生成周月报 AI 摘要的那条路径
    （refresh_service._regenerate_period_reports）拿的是 build_period_payload
    的原始结果，不受影响——那边确实需要正文。

    分类：周月报页面是前端自己按 focus 分板块的（日报的分区由后端给），
    而前端的 focusCategory 没有后端 infer_focus_category 那套关键词回退，
    也不拿 category 兜底——同一条目后端记在「产品工具」、前端摆进「未分类」，
    综述与板块就对不上了。在出口处解析一次写回，前端那一步只会命中「显式
    focus 有效」这条分支，两边永远同一个答案。"""
    slimmed = []
    for item in items:
        cleaned = {
            key: value for key, value in item.items() if key not in PERIOD_ITEM_HEAVY_FIELDS
        }
        resolved = resolve_focus_category(
            cleaned.get("focus_category"),
            cleaned.get("scoring_category") or cleaned.get("category"),
        )
        if resolved:
            cleaned["focus_category"] = resolved
        slimmed.append(cleaned)
    return slimmed


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


def build_latest_payload(
    daily_report_json: dict[str, Any],
    *,
    category: str | None = None,
    focus: str | None = None,
    tag: str | None = None,
    q: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    items = [
        item
        for item in daily_report_json.get("items", [])
        if _item_matches(item, category=category, focus=focus, tag=tag, q=q)
    ]
    total = len(items)
    page = items[offset : offset + limit] if limit is not None else items[offset:]
    return {
        "report_date": daily_report_json.get("report_date"),
        "updated_at": daily_report_json.get("updated_at"),
        "article_count": len(page),
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": page,
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
        # AI 主线与分类简述。summary_status 不是 generated 时 mainline_* 是
        # 空串，页面据此整块不渲染——不要只看有没有字段。
        "mainline_title": daily_report_json.get("mainline_title") or "",
        "mainline_body": daily_report_json.get("mainline_body") or "",
        "category_notes": daily_report_json.get("category_notes") or [],
        "summary_status": daily_report_json.get("summary_status") or "pending",
        "summary_generated_at": daily_report_json.get("summary_generated_at"),
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
    category: str | None = None,
    focus: str | None = None,
    tag: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    start_date = end_date - timedelta(days=6)
    items = repository.get_all_event_items_between(
        start_date,
        end_date,
        selected_only=True,
    )
    # 精选流按事件去重：一个事件只出它的代表条(is_main)，同热点榜的口径
    # (build_hotspots_payload)。2026-07-13 的"每篇文章独立成条"仍然适用于
    # /all 和后台——那里要的是完整的信源账本；精选流要的是"今天发生了什么"，
    # 同一件事铺三张卡只会把版面挤满。
    #
    # 副作用得认：代表条自己未入选(信源等级压过分数，见 choose_main_article)
    # 时，这个事件在精选流里就只剩这一条低分卡；代表条若被隐藏，整个事件
    # 也不再有替补顶上。两者都比"同一事件重复出现"好收拾。
    items = [
        item
        for item in items
        if item.get("is_main", True)
        and _item_matches(item, category=category, focus=focus, tag=tag, q=q)
    ]
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

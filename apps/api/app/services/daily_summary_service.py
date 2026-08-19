"""Daily report AI summary: one mainline over the day's multi-source events,
plus one short note per focus category.

Two deliberately different scopes, so the two blocks do not say the same thing:

- The mainline is written from the day's **multi-source** events only - the
  ones at least two independent sources reported. That is the day's news, as
  opposed to the day's reading list, and it cuts across categories.
- Each category note is written from that category's **whole** day, so it
  answers "what moved in 模型动态 today" rather than re-telling whichever of
  its events happened to be multi-source.

Both come from a single AI call. Per-category calls would be five times the
requests and let the notes contradict each other and the mainline; one call
sees everything at once. The pipeline runs 12-14 times a day, so the summary
is also fingerprinted (see summary_digest) and only re-bought when the day's
material actually changed.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timezone
from typing import Any

from app.services.taxonomy import FOCUS_CATEGORIES, resolve_focus_category

logger = logging.getLogger(__name__)

#: Events fed to the mainline. A day has 1-11 multi-source events in practice,
#: so this only ever bites on an unusually busy day.
MAINLINE_ITEM_LIMIT = 20

#: Items per category fed to the note. Only titles are sent - a 50-70 character
#: note does not need summaries, and dropping them is what keeps the whole
#: payload well inside the request budget with five categories in play
#: (measured 1.9k of the 8k limit on a 25-item day).
#:
#: 20, not 10: at 10 the cut fired almost daily (8 of the 10 days to 2026-08-19
#: had a category over 10 items; product hit 22), so a note claiming to cover
#: the category's whole day was routinely written from half of it. At 20 the
#: cut is back to being a fuse for extreme days - one day in those ten would
#: lose 2 tail items - and the heaviest measured day (58 items) still stays
#: around 3k of the 8k request budget.
CATEGORY_ITEM_LIMIT = 20

#: Minimum mainline length before one retry is spent. As with the weekly and
#: monthly reports, the floor sits below what the prompt asks: a short but real
#: mainline still beats no mainline, so the second attempt is published
#: whatever its length.
MAINLINE_BODY_MIN_CHARS = 60

SUMMARY_ATTEMPTS = 2

_FOCUS_LABELS = dict(FOCUS_CATEGORIES)


def _score(item: dict[str, Any]) -> float:
    try:
        return float(item.get("final_score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _source_count(item: dict[str, Any]) -> int:
    try:
        return max(int(item.get("source_count") or 1), 1)
    except (TypeError, ValueError):
        return 1


def is_multi_source(item: dict[str, Any]) -> bool:
    return _source_count(item) > 1


def sort_daily_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """多信源的一组在前，单信源的一组在后，各自组内按分数降序。

    刻意不按 (信源数, 分数) 整体降序——那样 3 个信源 60.5 分的条目会排在
    2 个信源 89.1 分的前面。「被多家报道」是一个是非题，不是一个可以和
    分数换算的量纲；它只决定进哪一组，组内仍然由分数说了算。

    一天之内所有条目由同一个模型打分，所以这里比较原始分是安全的。跨天
    聚合（周报月报）不能这么比，见 api/public.py 的 sort_period_items。

    同分同信源时用 event_id 兜底，让顺序只由内容决定、不由入参顺序决定。
    不这么做的话，同一批事件换个顺序传进来就会排出不同的结果，进而算出
    不同的 summary_digest——本该跳过的那次运行会白买一遍同样的文字。
    """

    def key(item: dict[str, Any]) -> tuple[float, str]:
        return (-_score(item), str(item.get("event_id") or ""))

    multi = sorted((item for item in items if is_multi_source(item)), key=key)
    single = sorted((item for item in items if not is_multi_source(item)), key=key)
    return multi + single


def group_by_focus_category(
    items: list[dict[str, Any]],
) -> list[tuple[str, str, list[dict[str, Any]]]]:
    """(key, label, items) for每个当天真有内容的分类，按 FOCUS_CATEGORIES 固定顺序。

    当天 0 条的分类不会出现在结果里——页面按这个列表渲染，所以空分类不会
    留下一个「暂无内容」的空壳板块。
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        key = resolve_focus_category(
            item.get("focus_category"),
            item.get("scoring_category") or item.get("category"),
        )
        grouped.setdefault(str(key), []).append(item)
    return [
        (key, label, sort_daily_items(grouped[key]))
        for key, label in FOCUS_CATEGORIES
        if grouped.get(key)
    ]


def build_summary_input(items: list[dict[str, Any]]) -> dict[str, Any]:
    """What the model is shown. Also the thing that gets fingerprinted, so a
    change here intentionally invalidates every stored digest."""
    mainline_items = sort_daily_items([item for item in items if is_multi_source(item)])
    return {
        "mainline_events": [
            {
                "title": str(item.get("title") or "")[:70],
                "summary": str(item.get("one_line_summary") or item.get("summary") or "")[:110],
                "category": str(item.get("focus_category") or item.get("category") or ""),
                "source_count": _source_count(item),
            }
            for item in mainline_items[:MAINLINE_ITEM_LIMIT]
        ],
        "categories": [
            {
                "category": key,
                "label": label,
                "item_count": len(group),
                # titles only: a 50-70 character note does not need summaries,
                # and five categories' worth of them would crowd the request
                "titles": [str(item.get("title") or "")[:60] for item in group[:CATEGORY_ITEM_LIMIT]],
            }
            for key, label, group in group_by_focus_category(items)
        ],
    }


def summary_digest(summary_input: dict[str, Any]) -> str:
    """Fingerprint of the material. Equal digest -> the call would see the same
    input, so the stored text is reused instead of paid for again."""
    canonical = json.dumps(summary_input, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_daily_summary_payload(payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("mainline_title") or "").strip()
    body = str(payload.get("mainline_body") or "").strip()
    if not title or not body:
        raise ValueError("daily summary payload missing mainline_title/mainline_body")
    notes: list[dict[str, str]] = []
    for note in payload.get("category_notes") or []:
        if not isinstance(note, dict):
            continue
        key = str(note.get("category") or "").strip()
        text = str(note.get("note") or "").strip()
        if key in _FOCUS_LABELS and text:
            notes.append({"category": key, "label": _FOCUS_LABELS[key], "note": text})
    return {"mainline_title": title, "mainline_body": body, "category_notes": notes}


def empty_summary(status: str = "skipped") -> dict[str, Any]:
    return {
        "mainline_title": "",
        "mainline_body": "",
        "category_notes": [],
        "status": status,
        "digest": None,
        "generated_at": None,
    }


def build_daily_summary(
    *,
    report_date: date,
    items: list[dict[str, Any]],
    ai_provider: Any,
    previous_digest: str | None = None,
) -> dict[str, Any] | None:
    """Write the day's mainline and category notes, or None to keep what is
    already stored.

    None (rather than a payload) is returned when the material is unchanged -
    the caller must not overwrite the stored text with a fresh AI call it did
    not need to make.
    """
    if not items:
        return empty_summary()

    summary_input = build_summary_input(items)
    if not summary_input["mainline_events"]:
        # 当天没有任何多信源事件（8/1、8/2 就是这样）。按约定不生成主线，
        # 页面整块不渲染——与其编一段，不如不写。分类简述同样跳过：它们
        # 和主线是一次调用出来的，没有主线可写时不值得单独再发一次请求。
        return empty_summary()
    if previous_digest and previous_digest == summary_digest(summary_input):
        return None

    summary: dict[str, Any] | None = None
    for attempt in range(1, SUMMARY_ATTEMPTS + 1):
        try:
            drafted = ai_provider.summarize_daily(summary_input, report_date.isoformat())
            drafted = parse_daily_summary_payload(drafted)
        except Exception:
            logger.warning(
                "daily summary attempt %d/%d failed for %s",
                attempt,
                SUMMARY_ATTEMPTS,
                report_date,
                exc_info=True,
            )
            continue
        summary = drafted
        if len(drafted["mainline_body"]) >= MAINLINE_BODY_MIN_CHARS:
            break
        logger.warning(
            "daily mainline for %s is %d chars (min %d) on attempt %d/%d",
            report_date,
            len(drafted["mainline_body"]),
            MAINLINE_BODY_MIN_CHARS,
            attempt,
            SUMMARY_ATTEMPTS,
        )
    if summary is None:
        # 没有确定性兜底文案：主线写不出来就不显示。周月报那边保留兜底是
        # 因为它至少点出了本期头条，而日报的头条就在下面的列表里，再复述
        # 一遍只是噪声。
        return empty_summary(status="failed")

    return {
        **summary,
        "status": "generated",
        "digest": summary_digest(summary_input),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

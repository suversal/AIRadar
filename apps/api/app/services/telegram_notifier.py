"""Telegram sync-report notifications (2026-07-12 night decision): after
every automatic/manual sync, push the full per-source outcome to the
admin's Telegram chat. Best-effort throughout - a notification failure
must never affect the pipeline run itself.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

TELEGRAM_MAX_MESSAGE_LENGTH = 4000
_STATUS_LABELS = {"succeeded": "✅ 成功", "failed": "❌ 失败"}


def _ingested_count(entry: dict[str, Any]) -> int:
    # 兼容修复前写入的历史 last_crawl_result(没有 ingested_count 字段)
    ingested = entry.get("ingested_count")
    if ingested is not None:
        return int(ingested)
    return int(entry.get("accepted_count") or 0)


def _sorted_source_entries(
    source_report: dict[str, dict[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    # 失败源排最前,其余按入库数降序 - 与后台运行明细同一口径(2026-07-13
    # 改为入库而非精选:精选数太稀疏,排序几乎没有区分度)
    def sort_key(item: tuple[str, dict[str, Any]]) -> tuple[int, int]:
        _source_id, entry = item
        failed = entry.get("status") != "ok"
        return (0 if failed else 1, -_ingested_count(entry))

    return sorted(source_report.items(), key=sort_key)


def format_sync_report(
    *,
    status: str,
    report_date: str,
    raw_count: int = 0,
    duplicate_count: int = 0,
    non_ai_dropped_count: int = 0,
    new_raw_count: int = 0,
    new_selected_count: int = 0,
    cluster_count: int = 0,
    source_report: dict[str, dict[str, Any]] | None = None,
    source_names: dict[str, str] | None = None,
    error: str | None = None,
) -> str:
    """Pure formatter (testable without network): the full per-source sync
    outcome as a Telegram-ready message."""
    source_names = source_names or {}
    status_label = _STATUS_LABELS.get(status, status)
    lines = [f"🛰 AI·RADAR 同步 {status_label} · {report_date}"]

    if status != "succeeded":
        lines.append(f"错误：{error or '未知错误'}")
        return "\n".join(lines)

    lines.append(
        f"抓取 {raw_count} = 重复 {duplicate_count} + 非AI {non_ai_dropped_count} + "
        f"入库 {new_raw_count}"
    )
    lines.append(f"精选 {new_selected_count} · 事件簇 {cluster_count}")

    entries = _sorted_source_entries(source_report or {})
    failed_lines: list[str] = []
    active_lines: list[str] = []
    idle_names: list[str] = []
    for source_id, entry in entries:
        name = source_names.get(source_id, source_id)
        if entry.get("status") != "ok":
            error_text = entry.get("error") or "未知错误"
            failed_lines.append(f"❌ {name}：{error_text}")
            continue
        fetched = entry.get("fetched_count") or 0
        if not fetched:
            # 这一轮 feed 里压根没有新条目,列明细纯属噪音,归进底部汇总
            idle_names.append(name)
            continue
        accepted = entry.get("accepted_count") or 0
        ingested = _ingested_count(entry)
        active_lines.append(f"✅ {name}：入库 {ingested} · 精选 {accepted} / 抓取 {fetched}")

    if failed_lines or active_lines:
        lines.append("")
        lines.append(f"信源明细（{len(active_lines)}/{len(entries)} 有更新）：")
        lines.extend(failed_lines)
        lines.extend(active_lines)

    if idle_names:
        lines.append("")
        lines.append(f"⚪ 本轮无抓取（{len(idle_names)}）：{'、'.join(idle_names)}")

    return "\n".join(lines)


def send_telegram_message(
    text: str,
    *,
    bot_token: str | None = None,
    chat_id: str | None = None,
) -> bool:
    """Best-effort push. Returns whether the send actually succeeded;
    callers must never let this raise or block the pipeline."""
    token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    chat = chat_id or os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False

    if len(text) > TELEGRAM_MAX_MESSAGE_LENGTH:
        text = text[:TELEGRAM_MAX_MESSAGE_LENGTH] + "\n…（消息过长，已截断）"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode("utf-8")
    request = urllib.request.Request(url, data=payload)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
            return bool(body.get("ok"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return False
    except Exception:  # pragma: no cover - defensive: never break the caller
        return False

"""SourcePilot X 推文同步（接入方案 Phase 4）。

数据链：SP `GET /api/v1/x/tweets` → 本地 `x_tweets` 表 → 随整库同步上云 → `/x` 页。
符合资格的新原创推文会在同一轮刷新中从数据库镜像转换为 ``RawArticle``，
复用既有 LLM 管线；本模块仍是唯一网络入口，不会因精选接入再抓一次。

## 内容边界：必须按订阅 handle 拉取

SP 的 `/x/tweets` 刻意不分 collected/searched（契约 §5.4——那张表记的是
「这条推文长什么样」，谁触发的抓取不改变这个事实），所以任何人现查
`search_x` 捞回的无关推文也在里面（实测见过 Vodafone 宽带砍价的路人回复）。
**不带 handle 全量拉会把这些杂音直接搬进 AR 的展示面**。逐 handle 拉取
（`?handle=`）就是 AR 侧的内容边界，与「信息流的内容边界由订阅配置决定」
（契约 §5.3）同一原则。

## 水位：往回多看几天，不是只追最新

`since` 按发推时间过滤（`created_at >`）。水位若取「库内最新推文时间」，
两类后到的更新会永远拿不到：互动数随 SP 重抓刷新、长文正文
（article_markdown）是每篇单独补取的（单轮有上限，剩下的下轮才有）。
所以 since = 库内最新时间往回退 REFRESH_MARGIN，重叠部分靠 tweet_id
upsert 覆盖旧行——幂等，不会重复。

水位从库里算而不是另存文件：SourcePilotCrawler 那边「fetch 时推进水位、
落库失败就永久漏文章」的坑（we-mp-rss #440）在这里不存在——since 的基准
就是「已成功落库的最新一条」，同一事务内先拉后写，写失败下轮自动重拉。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from app.crawlers.base import fetch_url_text

logger = logging.getLogger(__name__)

#: 与 SourcePilot `config/sources/x.yaml` 的 accounts 保持一致。
#: SP 没有暴露「订阅了哪些 handle」的端点，只能镜像一份；两边不一致的
#: 后果是漏账号（这边少配）或空拉（这边多配），都不损坏数据。
#: 可用环境变量 SOURCEPILOT_X_HANDLES（逗号分隔）覆盖，免改代码。
DEFAULT_X_HANDLES = [
    "OpenAI",
    "AnthropicAI",
    "claudeai",
    "ClaudeDevs",
    "GoogleAI",
    "GoogleDeepMind",
    "xai",
    "grok",
    "AIatMeta",
    "MicrosoftAI",
    "MistralAI",
    "huggingface",
    "nvidia",
    "deepseek_ai",
    "Alibaba_Qwen",
    "Kimi_Moonshot",
    "Zai_org",
    "TencentHunyuan",
    "ManusAI",
    "thsottiaux",
    "xiaohu",
    "dotey",
]

#: 与 SP x.yaml 的 topics[].name 保持一致（SP 契约 §5.5 话题订阅）。
#: 话题推文的作者不在订阅账号列表里，逐 handle 拉取覆盖不到它们，
#: 必须按话题单独拉。环境变量 SOURCEPILOT_X_TOPICS 覆盖。
DEFAULT_X_TOPICS = ["AI热点", "U卡推荐", "eSIM推荐"]

_PAGE_LIMIT = 200  # /x/tweets 的 limit 上限
_REFRESH_MARGIN = timedelta(days=3)


def _base_url() -> str:
    return os.getenv("SOURCEPILOT_BASE_URL", "http://127.0.0.1:8420").rstrip("/")


def configured_handles() -> list[str]:
    raw = os.getenv("SOURCEPILOT_X_HANDLES", "")
    handles = [h.strip().lstrip("@") for h in raw.split(",") if h.strip()]
    return handles or list(DEFAULT_X_HANDLES)


def configured_topics() -> list[str]:
    raw = os.getenv("SOURCEPILOT_X_TOPICS", "")
    topics = [t.strip() for t in raw.split(",") if t.strip()]
    return topics or list(DEFAULT_X_TOPICS)


def _check_contract_version(meta: dict) -> None:
    version = str(meta.get("contract_version") or "")
    if version and not version.startswith("1."):
        logger.error(
            "sourcepilot contract major version changed: %s - "
            "breaking changes possible, review the x tweets sync",
            version,
        )


def fetch_handle_tweets(handle: str, since: datetime | None) -> list[dict[str, Any]]:
    """拉一个 handle 的推文（按订阅账号守内容边界的那条腿）。"""
    return _fetch_tweets({"handle": handle}, since)


def fetch_topic_tweets(topic: str, since: datetime | None) -> list[dict[str, Any]]:
    """拉一个订阅话题的推文（SP 契约 §5.5，?topic= 过滤）。
    话题在 SP 侧就是订阅配置，所以这也是内容边界之内的拉取。"""
    return _fetch_tweets({"topic": topic}, since)


def _fetch_tweets(
    filters: dict[str, Any], since: datetime | None
) -> list[dict[str, Any]]:
    """ok:false 时 RATE_LIMITED 静默空手而归（SP 自己有冷却状态机，
    别叠加重试去捅），其余错误抛出让上层记账。"""
    params: dict[str, Any] = {**filters, "limit": _PAGE_LIMIT}
    if since is not None:
        params["since"] = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = fetch_url_text(
        f"{_base_url()}/api/v1/x/tweets?{urlencode(params)}",
        accept="application/json",
        timeout=15,
    )
    payload = json.loads(text)
    _check_contract_version(payload.get("meta") or {})
    if not payload.get("ok"):
        error = payload.get("error") or {}
        code = error.get("code")
        if code == "RATE_LIMITED":
            logger.warning("sourcepilot rate limited for x tweets %s", filters)
            return []
        raise RuntimeError(f"sourcepilot {code}: {error.get('message')}")
    return (payload.get("data") or {}).get("tweets") or []


def sync_x_tweets(
    repository: Any,
    handles: list[str] | None = None,
    topics: list[str] | None = None,
) -> dict[str, Any]:
    """逐 handle + 逐话题增量同步进 x_tweets 表。单个失败不拖垮其它。

    两条腿都要跑：handle 覆盖订阅账号的推文，topic 覆盖事件追踪捞回的
    （作者不在订阅列表里，handle 腿够不到）。同一条推文两边都命中时
    upsert 幂等合并。返回分项报告，供 crawl report / 日志观测。
    """
    from app.services.x_tweet_articles import (
        eligible_tweet_ids,
        pipeline_source_id_for_tweet,
    )

    resolved_handles = handles or configured_handles()
    subscribed_handles = {handle.strip().lstrip("@").lower() for handle in resolved_handles}
    report: dict[str, Any] = {"handles": {}, "topics": {}, "inserted": 0, "updated": 0}

    def _pull(entry_key: str, bucket: str, fetch, watermark_kwargs: dict[str, Any]) -> None:
        entry: dict[str, Any] = {"fetched": 0, "inserted": 0, "updated": 0, "error": None}
        try:
            watermark = repository.latest_x_tweet_created_at(**watermark_kwargs)
            since = watermark - _REFRESH_MARGIN if watermark else None
            tweets = fetch(since)
            entry["fetched"] = len(tweets)
            if tweets:
                eligible_ids = eligible_tweet_ids(tweets, subscribed_handles)
                pipeline_sources = {
                    tweet_id: source_id
                    for tweet in tweets
                    if (tweet_id := str(tweet.get("tweet_id") or "")) in eligible_ids
                    and (
                        source_id := pipeline_source_id_for_tweet(
                            tweet, subscribed_handles
                        )
                    )
                }
                result = repository.upsert_x_tweets(
                    tweets,
                    article_pipeline_sources=pipeline_sources,
                )
                entry["inserted"] = result.inserted
                entry["updated"] = result.updated
                report["inserted"] += result.inserted
                report["updated"] += result.updated
        except Exception as exc:
            logger.warning("x tweets sync failed for %s=%s: %s", bucket, entry_key, exc)
            entry["error"] = str(exc)
        report[bucket][entry_key] = entry

    for handle in resolved_handles:
        _pull(
            handle,
            "handles",
            lambda since, h=handle: fetch_handle_tweets(h, since),
            {"handle": handle},
        )
    for topic in topics if topics is not None else configured_topics():
        _pull(
            topic,
            "topics",
            lambda since, t=topic: fetch_topic_tweets(t, since),
            {"topic": topic},
        )
    return report

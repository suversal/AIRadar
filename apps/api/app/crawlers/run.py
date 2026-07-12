from __future__ import annotations

import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlsplit

from app.crawlers.base import BaseCrawler
from app.crawlers.registry import crawler_for_source
from app.models.domain import RawArticle, Source

CrawlerFactory = Callable[[Source], BaseCrawler]

SAME_DOMAIN_DELAY_SECONDS = 6.0
DEFAULT_CRAWL_CONCURRENCY = 8


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# 每源条数配置已停用(2026-07-12 深夜):feed 全量拉元数据(单请求,
# 成本恒定),总量由"只处理当天发布"的日期过滤控制,正文按需拉取


def _crawl_domain_group(
    group: list[Source],
    *,
    crawler_factory: CrawlerFactory,
) -> dict[str, dict]:
    """Fetch one domain's sources serially, honoring the politeness delay."""
    results: dict[str, dict] = {}
    previous_fetch: float | None = None
    for source in group:
        if previous_fetch is not None:
            wait_seconds = SAME_DOMAIN_DELAY_SECONDS - (time.monotonic() - previous_fetch)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
        previous_fetch = time.monotonic()
        source_started = time.perf_counter()
        try:
            fetched = crawler_factory(source).fetch(limit=None)
        except Exception as exc:  # keep one source failure from blocking the full pass
            results[source.id] = {
                "status": "skipped",
                "articles": [],
                "duration_ms": round((time.perf_counter() - source_started) * 1000, 2),
                "error": str(exc),
            }
            continue
        results[source.id] = {
            "status": "ok",
            "articles": fetched,
            "duration_ms": round((time.perf_counter() - source_started) * 1000, 2),
            "error": None,
        }
    return results


def crawl_sources(
    sources: list[Source],
    *,
    crawler_factory: CrawlerFactory = crawler_for_source,
    concurrency: int = DEFAULT_CRAWL_CONCURRENCY,
) -> tuple[list[RawArticle], dict]:
    """Crawl every active source for its own configured crawl_limit
    (unconfigured = everything the feed/API provides) - each source's budget
    is independent, there is no shared global pool to ration across sources."""
    active_sources = [source for source in sources if source.is_active]
    started_at = _utc_now_iso()

    domain_groups: dict[str, list[Source]] = {}
    for source in active_sources:
        domain = urlsplit(source.url).netloc.lower()
        domain_groups.setdefault(domain, []).append(source)

    results_by_source: dict[str, dict] = {}
    max_workers = max(1, min(concurrency, len(domain_groups) or 1))
    if max_workers == 1:
        for group in domain_groups.values():
            results_by_source.update(
                _crawl_domain_group(group, crawler_factory=crawler_factory)
            )
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(_crawl_domain_group, group, crawler_factory=crawler_factory)
                for group in domain_groups.values()
            ]
            for future in futures:
                results_by_source.update(future.result())

    articles: list[RawArticle] = []
    skipped = Counter()
    per_source: dict[str, dict] = {}
    for source in active_sources:
        result = results_by_source[source.id]
        if result["status"] == "skipped":
            skipped[f"{source.id}:fetch_failed"] += 1
            per_source[source.id] = {
                "status": "skipped",
                "article_count": 0,
                "duration_ms": result["duration_ms"],
                "error": result["error"],
            }
            continue
        fetched = result["articles"]
        articles.extend(fetched)
        per_source[source.id] = {
            "status": "ok",
            "article_count": len(fetched),
            "fetched_count": len(fetched),
            "duration_ms": result["duration_ms"],
            "error": None,
        }

    report = {
        "run_started_at": started_at,
        "run_finished_at": _utc_now_iso(),
        "source_count": len(active_sources),
        "article_count": len(articles),
        "per_source": per_source,
        "skipped_reasons": dict(skipped),
    }
    return articles, report

from __future__ import annotations

import time
from collections import Counter
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlsplit

from app.crawlers.base import BaseCrawler
from app.crawlers.registry import crawler_for_source
from app.models.domain import RawArticle, Source

CrawlerFactory = Callable[[Source], BaseCrawler]

SAME_DOMAIN_DELAY_SECONDS = 6.0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def crawl_sources(
    sources: list[Source],
    *,
    limit: int,
    crawler_factory: CrawlerFactory = crawler_for_source,
) -> tuple[list[RawArticle], dict]:
    active_sources = [source for source in sources if source.is_active]
    per_source_limit = max(1, limit // max(1, len(active_sources)))
    articles: list[RawArticle] = []
    skipped = Counter()
    per_source: dict[str, dict] = {}
    started_at = _utc_now_iso()

    last_fetch_by_domain: dict[str, float] = {}
    for source in active_sources:
        domain = urlsplit(source.url).netloc.lower()
        previous_fetch = last_fetch_by_domain.get(domain)
        if previous_fetch is not None:
            wait_seconds = SAME_DOMAIN_DELAY_SECONDS - (time.monotonic() - previous_fetch)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
        last_fetch_by_domain[domain] = time.monotonic()
        source_started = time.perf_counter()
        try:
            fetched = crawler_factory(source).fetch(limit=per_source_limit)
        except Exception as exc:  # keep one source failure from blocking the full pass
            skipped[f"{source.id}:fetch_failed"] += 1
            per_source[source.id] = {
                "status": "skipped",
                "article_count": 0,
                "duration_ms": round((time.perf_counter() - source_started) * 1000, 2),
                "error": str(exc),
            }
            continue

        remaining = max(0, limit - len(articles))
        accepted = fetched[:remaining]
        articles.extend(accepted)
        per_source[source.id] = {
            "status": "ok",
            "article_count": len(accepted),
            "fetched_count": len(fetched),
            "duration_ms": round((time.perf_counter() - source_started) * 1000, 2),
            "error": None,
        }
        if len(articles) >= limit:
            break

    report = {
        "run_started_at": started_at,
        "run_finished_at": _utc_now_iso(),
        "limit": limit,
        "source_count": len(active_sources),
        "article_count": len(articles),
        "per_source_limit": per_source_limit,
        "per_source": per_source,
        "skipped_reasons": dict(skipped),
    }
    return articles, report

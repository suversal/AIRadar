"""Shared full-page article fetching with a local cache.

Used by crawlers whose upstream feed carries little or no body text
(e.g. OpenAI's RSS has no description at all). Extracts the page's
<article>/<main> region into the standard original_* metadata contract.
Cached pages are invalidated when the semantic extractor version changes.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.crawlers.base import canonicalize_url, fetch_url_text, stable_hash
from app.crawlers.sitemap import extract_page_article, main_content_region
from app.crawlers.article_content import (
    CONTENT_EXTRACTION_VERSION,
    _detect_body_language,
    extract_article_content,
    extract_page_byline,
    profile_for_url,
)
from app.models.domain import RawArticle
from app.services.source_policy import is_unfetchable_article_domain

DEFAULT_PAGE_CACHE_DIR = Path("data") / "page_cache"
logger = logging.getLogger(__name__)

# 正文拉取跑在 AI 并发池里(2026-07-12 流程重排),同域真实请求保持
# 最小间隔,防止 20 并发同时打 Reddit 这类限流站点;缓存命中不节流
_DOMAIN_MIN_INTERVAL_SECONDS = 2.0
_DOMAIN_REGISTRY_LOCK = threading.Lock()
_DOMAIN_LOCKS: dict[str, threading.Lock] = {}
_DOMAIN_LAST_FETCH: dict[str, float] = {}


def _throttle_domain(url: str) -> None:
    domain = urlparse(url).netloc.lower()
    if not domain:
        return
    with _DOMAIN_REGISTRY_LOCK:
        lock = _DOMAIN_LOCKS.setdefault(domain, threading.Lock())
    with lock:
        last = _DOMAIN_LAST_FETCH.get(domain)
        if last is not None:
            wait = _DOMAIN_MIN_INTERVAL_SECONDS - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        _DOMAIN_LAST_FETCH[domain] = time.monotonic()


def _is_bare_url(text: str) -> bool:
    # a meta description that's just a link (real case: a tweet whose only
    # "text" is a shortened media URL) is worse than no content at all if
    # shown as an article body - it isn't prose, it's a dead-end pointer
    return bool(re.fullmatch(r"https?://\S+", text.strip()))


def prefer_full_page_content(article: RawArticle, *, cache_dir: Path | None = None) -> None:
    """Replace an article's content with the real linked page's body, if it
    can be fetched and extracted. Best-effort: any crawler that only
    discovers articles (RSS feeds, HN/Reddit-style link aggregators) should
    call this, since their own feed/API metadata is frequently a lossy
    teaser or entirely empty - the real content always lives at the
    original URL. Leaves the article untouched on any failure."""
    if is_unfetchable_article_domain(article.source_url):
        # known anti-crawler-walled hosts (e.g. WeChat) never return real
        # article HTML - skip the network round-trip entirely rather than
        # risk storing their verification page as if it were the body
        return
    try:
        payload = fetch_page_payload(article.source_url, cache_dir=cache_dir or DEFAULT_PAGE_CACHE_DIR)
    except Exception:
        return
    if not payload:
        return
    article.content = payload["content"]
    article.metadata.update(payload["metadata"])
    article.metadata["content_origin"] = "full_page"
    blocks = article.metadata.get("original_blocks")
    if isinstance(blocks, list) and not any(
        isinstance(block, dict) and block.get("type") == "byline" for block in blocks
    ) and article.author:
        author: dict[str, str] = {"name": article.author}
        byline: dict[str, Any] = {"type": "byline", "author": author}
        if article.published_at:
            byline["published_at"] = article.published_at.isoformat()
        if article.source_name:
            byline["source"] = {"name": article.source_name}
        blocks.insert(0, byline)
    detected = _detect_body_language(article.content)
    if detected:
        article.language = detected


def fetch_page_payload(
    url: str,
    *,
    cache_dir: Path = DEFAULT_PAGE_CACHE_DIR,
) -> dict[str, Any] | None:
    cache_path = Path(cache_dir) / f"{stable_hash(canonicalize_url(url))}.json"
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cached_metadata = cached.get("metadata") or {}
            profile = profile_for_url(url)
            profile_matches = not profile or cached_metadata.get("content_profile") == profile.name
            if (
                int(cached_metadata.get("content_extraction_version") or 0)
                == CONTENT_EXTRACTION_VERSION
                and profile_matches
            ):
                return cached
        except (OSError, json.JSONDecodeError):
            pass

    _throttle_domain(url)
    page_html = fetch_url_text(url, accept="text/html, */*")
    title, description = extract_page_article(page_html)
    region = main_content_region(page_html, base_url=url)
    extracted = extract_article_content(region, base_url=url, title=title) if region else None
    if extracted and not extracted.get("author_detected"):
        byline = extract_page_byline(page_html, base_url=url)
        if byline:
            extracted["original_blocks"].insert(0, byline)
            extracted["author_detected"] = True

    if extracted and extracted["original_paragraphs"]:
        logger.info(
            "article content extracted url=%s version=%s profile=%s kept_blocks=%s "
            "filtered_blocks=%s author_detected=%s",
            url,
            CONTENT_EXTRACTION_VERSION,
            extracted["content_profile"],
            len(extracted["original_blocks"]),
            extracted["filtered_blocks"],
            extracted["author_detected"],
        )
        payload = {
            "title": title,
            "content": extracted["original_text"] or description,
            "metadata": {
                "original_paragraphs": extracted["original_paragraphs"],
                "original_images": extracted["original_images"],
                "original_blocks": extracted["original_blocks"],
                "original_text": extracted["original_text"],
                "content_extraction_version": CONTENT_EXTRACTION_VERSION,
                "content_profile": extracted["content_profile"],
                "content_extraction_diagnostics": {
                    "filtered_blocks": extracted["filtered_blocks"],
                    "author_detected": extracted["author_detected"],
                    "kept_blocks": len(extracted["original_blocks"]),
                },
            },
        }
    elif description and not _is_bare_url(description):
        # no <article>/<main> region (e.g. video/preview pages) but the page
        # still carries a real meta description - better than nothing
        payload = {
            "title": title,
            "content": description,
            "metadata": {
                "original_paragraphs": [description],
                "original_text": description,
                "original_images": [],
                "original_blocks": [{"type": "paragraph", "text": description}],
                "content_extraction_version": CONTENT_EXTRACTION_VERSION,
                "content_profile": "meta-description-v2",
            },
        }
    else:
        logger.warning(
            "article content extraction failed url=%s version=%s reason=no-semantic-content",
            url,
            CONTENT_EXTRACTION_VERSION,
        )
        return None

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # cache is an optimization; never fail the crawl over it
    return payload

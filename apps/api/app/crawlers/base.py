from __future__ import annotations

import hashlib
import re
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request

from app.models.domain import RawArticle, Source

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "ref"}

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 SuversalAIRadar/0.1"
)
FEED_ACCEPT_HEADER = (
    "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"
)
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}


def fetch_url_text(
    url: str,
    *,
    accept: str = FEED_ACCEPT_HEADER,
    timeout: int = 20,
    max_attempts: int = 3,
    backoff_seconds: float = 3.0,
) -> str:
    for attempt in range(max_attempts):
        request = Request(
            url,
            headers={"Accept": accept, "User-Agent": BROWSER_USER_AGENT},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except HTTPError as error:
            if error.code not in RETRYABLE_HTTP_STATUSES or attempt == max_attempts - 1:
                raise
            time.sleep(backoff_seconds * (attempt + 1))
    raise RuntimeError(f"unreachable retry loop for {url}")  # pragma: no cover


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query_items = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        lower_key = key.lower()
        if lower_key in TRACKING_QUERY_KEYS:
            continue
        if lower_key.startswith(TRACKING_QUERY_PREFIXES):
            continue
        query_items.append((key, value))
    query = urlencode(query_items, doseq=True)
    path = parts.path.rstrip("/") or parts.path
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_article(
    *,
    source: Source,
    source_url: str,
    title: str,
    content: str,
    author: str | None,
    published_at: datetime | None,
    language: str,
    raw_score: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
) -> RawArticle:
    canonical_url = canonicalize_url(source_url)
    clean_title = clean_text(title)
    clean_content = clean_text(content)
    published = published_at or datetime.now(timezone.utc)
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    url_hash = stable_hash(canonical_url)
    title_hash = stable_hash(clean_title.lower())
    article_id = stable_hash(f"{source.id}:{url_hash}")[:24]
    return RawArticle(
        id=article_id,
        source_id=source.id,
        source_name=source.name,
        source_role=source.source_role,
        source_tier=source.tier,
        source_url=canonical_url,
        title=clean_title,
        content=clean_content,
        author=clean_text(author) or None,
        published_at=published,
        language=language or source.language,
        raw_score=raw_score or {},
        metadata=metadata or {},
        title_hash=title_hash,
        url_hash=url_hash,
    )


class BaseCrawler:
    def __init__(self, source: Source):
        self.source = source

    def fetch(self, limit: int | None = None) -> list[RawArticle]:
        raise NotImplementedError


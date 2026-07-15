from __future__ import annotations

import hashlib
import re
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request

from app.models.domain import RawArticle, Source

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "ref"}

# full browser profile: cloudflare fronts (e.g. openai.com) return 403 to
# requests carrying crawler markers or missing fetch-metadata headers
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15"
)
FEED_ACCEPT_HEADER = (
    "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"
)
BROWSER_HEADERS = {
    "User-Agent": BROWSER_USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
# Python's urllib.request.HTTPRedirectHandler only auto-follows 301/302/303/307;
# 308 (Permanent Redirect) is a documented gap and surfaces as a raw HTTPError
MANUAL_REDIRECT_STATUSES = {308}
MAX_REDIRECTS = 5


def _fetch_via_curl(
    url: str, *, accept: str, timeout: int, user_agent: str, cookie: str | None = None
) -> str:
    """Some hosts (e.g. linux.do) TLS/JA3-fingerprint urllib's requests and
    return a Cloudflare challenge, but let a real curl binary through -
    confirmed by direct probe. Args are passed as a list (no shell=True), so
    there is no shell-injection surface even though url comes from source
    config."""
    args = [
            "curl",
            "-sS",
            "-L",
            "--max-time",
            str(timeout),
            "-A",
            user_agent,
            "-H",
            f"Accept: {accept}",
            "-H",
            f"Accept-Language: {BROWSER_HEADERS['Accept-Language']}",
        ]
    if cookie:
        args.extend(["-H", f"Cookie: {cookie}"])
    args.append(url)
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout + 5,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl exited {result.returncode} for {url}: {result.stderr.strip()}")
    return result.stdout


def fetch_url_text(
    url: str,
    *,
    accept: str = FEED_ACCEPT_HEADER,
    timeout: int = 10,
    max_attempts: int = 3,
    backoff_seconds: float = 3.0,
    use_curl: bool = False,
    cookie: str | None = None,
    # a handful of sources (currently just AI HOT, per their own API docs)
    # explicitly ask callers to identify themselves with a real, non-browser
    # UA instead of pretending to be a browser - everything else keeps
    # masquerading as Safari to get past Cloudflare-fronted sites
    user_agent: str = BROWSER_USER_AGENT,
    _redirects_followed: int = 0,
) -> str:
    if use_curl:
        for attempt in range(max_attempts):
            try:
                return _fetch_via_curl(
                    url, accept=accept, timeout=timeout, user_agent=user_agent, cookie=cookie
                )
            except (RuntimeError, subprocess.TimeoutExpired):
                if attempt == max_attempts - 1:
                    raise
                time.sleep(backoff_seconds * (attempt + 1))
        raise RuntimeError(f"unreachable curl retry loop for {url}")  # pragma: no cover
    for attempt in range(max_attempts):
        headers = {"Accept": accept, **BROWSER_HEADERS, "User-Agent": user_agent}
        if cookie:
            headers["Cookie"] = cookie
        request = Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except HTTPError as error:
            if error.code in MANUAL_REDIRECT_STATUSES:
                location = error.headers.get("Location") if error.headers else None
                if not location or _redirects_followed >= MAX_REDIRECTS:
                    raise
                return fetch_url_text(
                    urljoin(url, location),
                    accept=accept,
                    timeout=timeout,
                    max_attempts=max_attempts,
                    backoff_seconds=backoff_seconds,
                    user_agent=user_agent,
                    cookie=cookie,
                    _redirects_followed=_redirects_followed + 1,
                )
            if error.code not in RETRYABLE_HTTP_STATUSES or attempt == max_attempts - 1:
                raise
            time.sleep(backoff_seconds * (attempt + 1))
        except URLError:
            # transient network failures (SSL handshake timeout, DNS hiccup,
            # connection reset) deserve the same retry chance as a 5xx
            if attempt == max_attempts - 1:
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

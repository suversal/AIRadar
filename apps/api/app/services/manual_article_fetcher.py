from __future__ import annotations

import ipaddress
import os
import socket
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.crawlers.article_content import extract_article_content, extract_page_byline
from app.crawlers.sitemap import extract_page_article, main_content_region


class ManualFetchError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


DEFAULT_MAX_RESPONSE_BYTES = 8_000_000
HARD_MAX_RESPONSE_BYTES = 20_000_000


def manual_article_max_response_bytes() -> int:
    """Configurable decoded-response limit with a non-bypassable safety cap."""
    try:
        configured = int(
            os.getenv("MANUAL_ARTICLE_MAX_RESPONSE_BYTES", str(DEFAULT_MAX_RESPONSE_BYTES))
        )
    except ValueError:
        configured = DEFAULT_MAX_RESPONSE_BYTES
    return max(1, min(configured, HARD_MAX_RESPONSE_BYTES))


def validate_public_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ManualFetchError("invalid_url", "only public HTTP/HTTPS URLs are allowed")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise ManualFetchError("blocked_address", "local addresses are not allowed")
    try:
        addresses = {entry[4][0] for entry in socket.getaddrinfo(host, parsed.port or 443)}
    except socket.gaierror as exc:
        raise ManualFetchError("fetch_failed", "hostname could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ManualFetchError("blocked_address", "private or reserved addresses are not allowed")
    return parsed.geturl()


def _published_at_from_byline(byline: dict[str, Any] | None) -> str | None:
    if not byline:
        return None
    value = byline.get("published_at")
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


def fetch_manual_article(
    url: str,
    *,
    timeout_seconds: float = 15.0,
    max_bytes: int | None = None,
    max_redirects: int = 5,
) -> dict[str, Any]:
    max_bytes = manual_article_max_response_bytes() if max_bytes is None else max(1, max_bytes)
    current = validate_public_url(url)
    html = ""
    with httpx.Client(timeout=timeout_seconds, follow_redirects=False) as client:
        for _ in range(max_redirects + 1):
            request = client.build_request(
                "GET",
                current,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    # WeChat returns a verification shell to obvious crawler
                    # user agents even for a public article URL. Use a normal
                    # browser identity; SSRF, redirect and byte limits remain
                    # enforced independently below.
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36"
                    ),
                },
            )
            response = client.send(request, stream=True)
            try:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ManualFetchError("fetch_failed", "redirect response had no location")
                    current = validate_public_url(urljoin(current, location))
                    continue
                if not response.is_success:
                    raise ManualFetchError(
                        "fetch_failed", f"upstream returned HTTP {response.status_code}"
                    )
                content_type = response.headers.get("content-type", "").lower()
                if (
                    "text/html" not in content_type
                    and "application/xhtml+xml" not in content_type
                ):
                    raise ManualFetchError("fetch_failed", "upstream did not return HTML")
                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        declared_size = int(content_length)
                    except ValueError:
                        declared_size = 0
                    if declared_size > max_bytes:
                        raise ManualFetchError("fetch_failed", "upstream page is too large")
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise ManualFetchError("fetch_failed", "upstream page is too large")
                    chunks.append(chunk)
                encoding = response.encoding or "utf-8"
                html = b"".join(chunks).decode(encoding, errors="replace")
                break
            finally:
                response.close()
        else:
            raise ManualFetchError("fetch_failed", "too many redirects")
    title, description = extract_page_article(html)
    region = main_content_region(html, base_url=current)
    extracted = extract_article_content(region, base_url=current, title=title) if region else None
    byline = extract_page_byline(html, base_url=current)
    blocks = list((extracted or {}).get("original_blocks") or [])
    if byline and not (extracted or {}).get("author_detected"):
        blocks.insert(0, byline)
    content = str((extracted or {}).get("original_text") or description or "").strip()
    author = None
    if byline and isinstance(byline.get("author"), dict):
        author = str(byline["author"].get("name") or "").strip() or None
    return {
        "canonical_url": current,
        "title": str(title or "").strip(),
        "content": content,
        "author": author,
        "published_at": _published_at_from_byline(byline),
        "language": "zh" if any("\u4e00" <= char <= "\u9fff" for char in content[:1000]) else "en",
        "original_blocks": blocks,
        "original_paragraphs": list((extracted or {}).get("original_paragraphs") or ([content] if content else [])),
        "original_images": list((extracted or {}).get("original_images") or []),
        "content_origin": "manual_url_fetch",
    }

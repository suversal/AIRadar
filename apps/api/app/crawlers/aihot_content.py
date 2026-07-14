"""Fetches AI HOT's own /items/{id} permalink page and extracts both the
Chinese translation (already visible in the page's initial HTML) and the
English original (embedded in a Next.js React Server Components streaming
payload, only swapped in client-side by the "原文" toggle button - never a
separate network request) that AI HOT already produced.

This exists so the two AI HOT sources (aihot_feed/aihot_all, gated by their
`use_aihot_item_page` source config) don't need to re-fetch the third-party
original and re-translate it ourselves - see the plan note in
default_sources.py for why.

Fragile-on-purpose warning: the English-original extraction depends on
Next.js's internal RSC wire format (`self.__next_f.push([1, "..."])`), which
is not a documented/stable contract. If AI HOT redeploys their frontend with
a different framework or a materially different chunking scheme, English
extraction will silently stop finding a match and this degrades to
Chinese-only (best-effort, never raises) - it will not break the Chinese
side, which comes from plain visible DOM.

AI HOT's own API docs ask automated callers to identify themselves with a
real, non-browser User-Agent - see AIHOT_USER_AGENT.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.crawlers.article_content import extract_article_content
from app.crawlers.base import canonicalize_url, fetch_url_text, stable_hash
from app.crawlers.page_content import _throttle_domain
from app.crawlers.sitemap import _balanced_div_region

DEFAULT_PAGE_CACHE_DIR = Path("data") / "page_cache"

# identify ourselves instead of pretending to be a browser, per AI HOT's own
# OpenAPI docs ("脚本和后端服务必须设置能识别自己的非浏览器 User-Agent")
AIHOT_USER_AGENT = "Pixel"

_DT_ARTICLE_OPEN_RE = re.compile(
    r'<div\b[^>]*class="[^"]*\bdt-article\b[^"]*"[^>]*>', re.IGNORECASE
)

# Next.js RSC flight wire format: each streamed chunk is its own
# `self.__next_f.push([1, "<JSON-string-escaped payload>"])` script tag
_NEXT_F_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')

_CJK_RE = re.compile(r"[一-鿿]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_BLOCK_TAG_HINT_RE = re.compile(r"<(?:h[1-6]|p|figure|li)\b", re.IGNORECASE)
# a real article-length chunk, not a stray short string also carrying a
# couple of tag-looking characters
_MIN_LATIN_CHARS_FOR_ARTICLE = 200


def _decode_flight_chunk(raw: str) -> str | None:
    try:
        return json.loads(f'"{raw}"')
    except (json.JSONDecodeError, ValueError):
        return None


def _looks_like_english_article_html(text: str) -> bool:
    if len(_BLOCK_TAG_HINT_RE.findall(text)) < 3:
        return False
    latin = len(_LATIN_RE.findall(text))
    if latin < _MIN_LATIN_CHARS_FOR_ARTICLE:
        return False
    cjk = len(_CJK_RE.findall(text))
    return latin > cjk * 4


def _extract_english_original_html(page_html: str) -> str | None:
    candidates = []
    for match in _NEXT_F_PUSH_RE.finditer(page_html):
        decoded = _decode_flight_chunk(match.group(1))
        if decoded and _looks_like_english_article_html(decoded):
            candidates.append(decoded)
    if not candidates:
        return None
    # several chunks can incidentally match (e.g. a short English pull-quote
    # duplicated elsewhere on the page) - the real article body is the
    # longest one
    return max(candidates, key=len)


def _extract_chinese_body_html(page_html: str) -> str | None:
    match = _DT_ARTICLE_OPEN_RE.search(page_html)
    if not match:
        return None
    return _balanced_div_region(page_html, match)


def fetch_aihot_item_content(
    permalink_url: str, *, cache_dir: Path | None = None
) -> dict[str, Any] | None:
    """Best-effort: returns None on any failure or if neither language could
    be extracted, so the caller can leave the article's existing (thin RSS
    summary) content untouched rather than crash the whole crawl round."""
    cache_path = (cache_dir or DEFAULT_PAGE_CACHE_DIR) / (
        f"aihot-{stable_hash(canonicalize_url(permalink_url))}.json"
    )
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    try:
        _throttle_domain(permalink_url)
        page_html = fetch_url_text(
            permalink_url, accept="text/html, */*", user_agent=AIHOT_USER_AGENT
        )
    except Exception:
        return None

    chinese_html = _extract_chinese_body_html(page_html)
    english_html = _extract_english_original_html(page_html)
    if not chinese_html and not english_html:
        return None

    chinese = extract_article_content(chinese_html, base_url=permalink_url) if chinese_html else None
    english = extract_article_content(english_html, base_url=permalink_url) if english_html else None

    metadata: dict[str, Any] = {}
    if english and english["original_paragraphs"]:
        metadata["original_text"] = english["original_text"]
        metadata["original_paragraphs"] = english["original_paragraphs"]
        metadata["original_images"] = english["original_images"]
        metadata["original_blocks"] = english["original_blocks"]
    if chinese and chinese["original_paragraphs"]:
        metadata["translated_paragraphs"] = chinese["original_paragraphs"]
        metadata["translated_blocks"] = chinese["original_blocks"]
        metadata["translation_source_language"] = "en"
        metadata["translation_target_language"] = "zh"
        metadata["translation_status"] = "completed"
        # mirrors runner.py's translation_source_hash() exactly, duplicated
        # here (rather than imported) to avoid a circular import with
        # pipeline/runner.py, which imports this module
        metadata["translation_source_hash"] = stable_hash(
            "\n".join(chinese["original_paragraphs"])
        )[:16]

    if not metadata:
        return None

    if chinese and chinese["original_text"]:
        content = chinese["original_text"]
    elif english:
        content = english["original_text"]
    else:
        content = ""
    payload = {"content": content, "metadata": metadata}

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # cache is an optimization; never fail the crawl over it
    return payload

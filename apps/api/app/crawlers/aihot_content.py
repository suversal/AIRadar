"""Fetches AI HOT's own /items/{id} permalink page and extracts both the
Chinese DOM content (already visible in the page's initial HTML) and the
English content (embedded in a Next.js React Server Components streaming
payload, only swapped in client-side by the "原文" toggle button - never a
separate network request) that AI HOT already produced.

Which of the two extracted blocks is actually "original" vs. AI HOT's own
translation is decided per-article by detected script (see
_assign_original_and_translation), not assumed to always be
English-original/Chinese-translation - AI HOT also aggregates zh-native
sources (e.g. WeChat articles), for which the DOM block is the true original
and the RSC chunk (if any) would be AI HOT's own translation of it.

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

from app.crawlers.article_content import (
    CONTENT_EXTRACTION_VERSION,
    _CJK_RE,
    _LATIN_RE,
    _detect_body_language,
    extract_article_content,
)
from app.crawlers.base import canonicalize_url, fetch_url_text, stable_hash
from app.crawlers.page_content import _throttle_domain
from app.crawlers.sitemap import _balanced_div_region

DEFAULT_PAGE_CACHE_DIR = Path("data") / "page_cache"

# identify ourselves instead of pretending to be a browser, per AI HOT's own
# OpenAPI docs ("脚本和后端服务必须设置能识别自己的非浏览器 User-Agent")
AIHOT_USER_AGENT = "HotAI/1.0"

_DT_BODY_OPEN_RE = re.compile(
    r'<div\b[^>]*class="[^"]*\bdt-(?:article|tweet)\b[^"]*"[^>]*>', re.IGNORECASE
)

# Next.js RSC flight wire format: each streamed chunk is its own
# `self.__next_f.push([1, "<JSON-string-escaped payload>"])` script tag
_NEXT_F_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')

_BLOCK_TAG_HINT_RE = re.compile(r"<(?:h[1-6]|p|figure|li)\b", re.IGNORECASE)
# a real article-length chunk, not a stray short string also carrying a
# couple of tag-looking characters
_MIN_LATIN_CHARS_FOR_ARTICLE = 200

# AI HOT's HTML route can return a small HTTP-200 JavaScript cookie challenge
# before the real Next.js page. Its public JSON endpoint does not include the
# item body, so reproduce that narrowly-scoped handshake and retry once.
_EO_CHALLENGE_STATUS_RE = re.compile(
    r"WTKkN:(\d+).*?bOYDu:(\d+).*?wyeCN:(\d+)", re.DOTALL
)
_EO_CHALLENGE_SSID_RE = re.compile(
    r'EO_Bot_Ssid=.*?\]\(t,(\d+)\);continue;case"4"', re.DOTALL
)


def _edge_challenge_cookie(page_html: str) -> str | None:
    if "EO_Bot_Ssid" not in page_html or "__tst_status" not in page_html:
        return None
    status_match = _EO_CHALLENGE_STATUS_RE.search(page_html)
    ssid_match = _EO_CHALLENGE_SSID_RE.search(page_html)
    if not status_match or not ssid_match:
        return None
    status = sum(int(value) for value in status_match.groups())
    return f"__tst_status={status}#; EO_Bot_Ssid={ssid_match.group(1)}"


def _fetch_aihot_page(permalink_url: str) -> str:
    page_html = fetch_url_text(
        permalink_url, accept="text/html, */*", user_agent=AIHOT_USER_AGENT
    )
    cookie = _edge_challenge_cookie(page_html)
    if cookie:
        page_html = fetch_url_text(
            permalink_url,
            accept="text/html, */*",
            user_agent=AIHOT_USER_AGENT,
            cookie=cookie,
        )
    return page_html


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
    # Long-form/RSS items use dt-article; X items use dt-tweet.
    match = _DT_BODY_OPEN_RE.search(page_html)
    if not match:
        return None
    return _balanced_div_region(page_html, match)


def _resolve_block_language(block: dict[str, Any] | None, *, default: str) -> str:
    if not block:
        return default
    return _detect_body_language(block["original_text"]) or default


def _assign_original_and_translation(
    dom_block: dict[str, Any] | None, rsc_block: dict[str, Any] | None
) -> tuple[dict[str, Any], str | None]:
    """Decide which of the two extracted blocks is the real "original" and
    which (if any) is AI HOT's own translation, based on actually detected
    script - rather than assuming the RSC/English chunk is always the
    original (that assumption breaks for zh-native sources AI HOT also
    aggregates, e.g. WeChat articles). When both sides resolve to the same
    detected language (heuristic drift, or no genuine translation pair
    exists), the longer side wins as "original" and no translation is
    recorded - two mismatched "originals" would be worse than treating it as
    monolingual."""
    if not dom_block and not rsc_block:
        return {}, None

    dom_lang = _resolve_block_language(dom_block, default="zh")
    rsc_lang = _resolve_block_language(rsc_block, default="en")

    translated: dict[str, Any] | None = None
    if dom_block and not rsc_block:
        original, language = dom_block, dom_lang
    elif rsc_block and not dom_block:
        original, language = rsc_block, rsc_lang
    elif dom_lang == rsc_lang:
        if len(dom_block["original_text"]) >= len(rsc_block["original_text"]):
            original, language = dom_block, dom_lang
        else:
            original, language = rsc_block, rsc_lang
    elif dom_lang == "zh":
        original, language, translated = rsc_block, rsc_lang, dom_block
    else:
        original, language, translated = dom_block, dom_lang, rsc_block

    metadata: dict[str, Any] = {
        "original_text": original["original_text"],
        "original_paragraphs": original["original_paragraphs"],
        "original_images": original["original_images"],
        "original_blocks": original["original_blocks"],
        "content_extraction_version": CONTENT_EXTRACTION_VERSION,
    }
    if translated and translated["original_paragraphs"]:
        metadata["translated_paragraphs"] = translated["original_paragraphs"]
        metadata["translated_blocks"] = translated["original_blocks"]
        metadata["translation_source_language"] = language
        metadata["translation_target_language"] = "zh"
        metadata["translation_status"] = "completed"
        # mirrors runner.py's translation_source_hash() exactly, duplicated
        # here (rather than imported) to avoid a circular import with
        # pipeline/runner.py, which imports this module
        metadata["translation_source_hash"] = stable_hash(
            "\n".join(translated["original_paragraphs"])
        )[:16]
    return metadata, language


def fetch_aihot_item_content(
    permalink_url: str, *, cache_dir: Path | None = None
) -> dict[str, Any] | None:
    """Best-effort: returns None on any failure or if neither block could be
    extracted, so the caller can leave the article's existing (thin RSS
    summary) content untouched rather than crash the whole crawl round."""
    cache_path = (cache_dir or DEFAULT_PAGE_CACHE_DIR) / (
        f"aihot-{stable_hash(canonicalize_url(permalink_url))}.json"
    )
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and isinstance(cached.get("metadata"), dict):
                cached["metadata"].setdefault(
                    "content_extraction_version", CONTENT_EXTRACTION_VERSION
                )
            return cached
        except (OSError, json.JSONDecodeError):
            pass

    try:
        _throttle_domain(permalink_url)
        page_html = _fetch_aihot_page(permalink_url)
    except Exception:
        return None

    chinese_html = _extract_chinese_body_html(page_html)
    english_html = _extract_english_original_html(page_html)
    if not chinese_html and not english_html:
        return None

    chinese = extract_article_content(chinese_html, base_url=permalink_url) if chinese_html else None
    english = extract_article_content(english_html, base_url=permalink_url) if english_html else None

    dom_block = chinese if chinese and chinese["original_paragraphs"] else None
    rsc_block = english if english and english["original_paragraphs"] else None

    metadata, language = _assign_original_and_translation(dom_block, rsc_block)
    if not metadata:
        return None

    payload = {"content": metadata["original_text"], "metadata": metadata, "language": language}

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # cache is an optimization; never fail the crawl over it
    return payload

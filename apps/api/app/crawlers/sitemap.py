from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from app.crawlers.article_content import extract_article_content
from app.crawlers.base import (
    BaseCrawler,
    canonicalize_url,
    clean_text,
    fetch_url_text,
    normalize_article,
    stable_hash,
)
from app.models.domain import RawArticle, Source

DEFAULT_MAX_PAGES = 8
DEFAULT_PAGE_CACHE_DIR = Path("data") / "page_cache"

_ARTICLE_REGION_RE = re.compile(r"<article\b.*?</article>", re.IGNORECASE | re.DOTALL)
_MAIN_REGION_RE = re.compile(r"<main\b.*?</main>", re.IGNORECASE | re.DOTALL)

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_RE = re.compile(
    r"<meta[^>]+(?:property|name)=[\"'](?:og:)?description[\"'][^>]*>",
    re.IGNORECASE,
)
_META_CONTENT_RE = re.compile(r"content=[\"'](.*?)[\"']", re.IGNORECASE | re.DOTALL)
_TITLE_SUFFIX_RE = re.compile(r"\s*[\\|·—-]\s*[^\\|·—-]*$")


def _parse_lastmod(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_sitemap_entries(
    xml_text: str, *, path_prefix: str
) -> list[tuple[str, datetime | None]]:
    root = ET.fromstring(xml_text)
    entries: list[tuple[str, datetime | None]] = []
    for url_element in root.iter():
        if url_element.tag.split("}")[-1] != "url":
            continue
        loc = None
        lastmod = None
        for child in url_element:
            local_name = child.tag.split("}")[-1]
            if local_name == "loc":
                loc = (child.text or "").strip()
            elif local_name == "lastmod":
                lastmod = _parse_lastmod(child.text)
        if not loc or not loc.startswith(path_prefix):
            continue
        if loc.rstrip("/") == path_prefix.rstrip("/"):
            continue
        entries.append((loc, lastmod))
    fallback = datetime.min.replace(tzinfo=timezone.utc)
    entries.sort(key=lambda entry: entry[1] or fallback, reverse=True)
    return entries


def main_content_region(html_text: str) -> str | None:
    match = _ARTICLE_REGION_RE.search(html_text)
    if match:
        return match.group(0)
    match = _MAIN_REGION_RE.search(html_text)
    if match:
        return match.group(0)
    return None


def extract_page_article(html_text: str) -> tuple[str, str]:
    title = ""
    title_match = _TITLE_RE.search(html_text)
    if title_match:
        title = clean_text(html.unescape(title_match.group(1)))
        title = _TITLE_SUFFIX_RE.sub("", title).strip()
    description = ""
    meta_match = _META_RE.search(html_text)
    if meta_match:
        content_match = _META_CONTENT_RE.search(meta_match.group(0))
        if content_match:
            description = clean_text(html.unescape(content_match.group(1)))
    return title, description


class SitemapCrawler(BaseCrawler):
    def __init__(self, source: Source, *, cache_dir: Path | None = None):
        super().__init__(source)
        self.cache_dir = Path(cache_dir) if cache_dir is not None else DEFAULT_PAGE_CACHE_DIR

    def _cache_path(self, loc: str) -> Path:
        return self.cache_dir / f"{stable_hash(canonicalize_url(loc))}.json"

    def _read_cached_page(self, loc: str, lastmod: datetime | None) -> dict | None:
        cache_path = self._cache_path(loc)
        if not cache_path.exists():
            return None
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        cached_lastmod = cached.get("lastmod")
        current_lastmod = lastmod.isoformat() if lastmod else None
        # refetch when the sitemap advertises a newer revision (or we cannot compare)
        if current_lastmod is None or cached_lastmod is None:
            return None
        if current_lastmod > cached_lastmod:
            return None
        return cached

    def _write_cached_page(self, loc: str, lastmod: datetime | None, payload: dict) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            payload = dict(payload)
            payload["lastmod"] = lastmod.isoformat() if lastmod else None
            self._cache_path(loc).write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass  # cache is an optimization; never fail the crawl over it

    def _extract_page_payload(self, loc: str, page_html: str) -> dict | None:
        title, description = extract_page_article(page_html)
        if not title:
            return None
        metadata: dict = {"crawler": "sitemap"}
        content = description
        region = main_content_region(page_html)
        if region:
            extracted = extract_article_content(region, base_url=loc)
            if extracted["original_paragraphs"]:
                metadata.update(
                    {
                        "original_paragraphs": extracted["original_paragraphs"],
                        "original_images": extracted["original_images"],
                        "original_blocks": extracted["original_blocks"],
                    }
                )
                content = extracted["original_text"] or description
        return {"title": title, "content": content, "metadata": metadata}

    def fetch(self, limit: int | None = None) -> list[RawArticle]:
        config = self.source.config or {}
        path_prefix = config.get("path_prefix") or self.source.homepage
        max_pages = int(config.get("max_pages") or DEFAULT_MAX_PAGES)
        if limit is not None:
            max_pages = min(max_pages, limit)

        sitemap_xml = fetch_url_text(self.source.url)
        entries = parse_sitemap_entries(sitemap_xml, path_prefix=path_prefix)

        articles: list[RawArticle] = []
        for loc, lastmod in entries[:max_pages]:
            payload = self._read_cached_page(loc, lastmod)
            if payload is None:
                page_html = fetch_url_text(loc, accept="text/html, */*")
                payload = self._extract_page_payload(loc, page_html)
                if payload is None:
                    continue
                self._write_cached_page(loc, lastmod, payload)
            articles.append(
                normalize_article(
                    source=self.source,
                    source_url=loc,
                    title=payload["title"],
                    content=payload["content"],
                    author=None,
                    published_at=lastmod,
                    language=self.source.language,
                    raw_score={},
                    metadata=dict(payload["metadata"]),
                )
            )
        return articles

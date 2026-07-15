from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from app.crawlers.article_content import (
    CONTENT_EXTRACTION_VERSION,
    extract_article_content,
    extract_page_byline,
)
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
# <aside> is the HTML5-semantic tag for tangentially-related content (e.g. a
# "Recent Articles" sidebar widget) - real cases had several such cards each
# individually exceed REGION_MIN_TEXT_CHARS, outscoring the actual article
# body and getting picked instead of it. Strip asides before scanning.
_ASIDE_RE = re.compile(r"<aside\b.*?</aside>", re.IGNORECASE | re.DOTALL)
# 显式"这里是正文"的容器类名（HuggingFace 的 blog-content、WordPress 的
# entry-content 等）。这类页面（真实案例：HF 博客）把评论区、推荐卡片和正文
# 平铺在同一个 <main> 里且没有 <aside>/<section> 语义标签——只有缩到正文
# 容器本身才能把 "Sign up or log in to comment" 这类 UI 文案挡在外面
_CONTENT_DIV_OPEN_RE = re.compile(
    r'<div\b[^>]*class="[^"]*\b(?:blog-content|entry-content|post-content|article-content|post-body|article-body)\b[^"]*"[^>]*>',
    re.IGNORECASE,
)
_DIV_TOKEN_RE = re.compile(r"<div\b[^>]*>|</div\s*>", re.IGNORECASE)

# WordPress 常见正文容器。这里只匹配开标签，再用深度计数找到它自己的
# 闭标签；绝不能贪婪到页面最后一个 </div>，否则作者列表和热门推荐都会
# 混入正文。
_WP_ARTICLE_DIV_OPEN_RE = re.compile(
    r'<div\b[^>]*class="[^"]*\b(?:article|entry-content|post-content|article-content)\b[^"]*"[^>]*>',
    re.IGNORECASE,
)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")

# 低于这个纯文本量的候选区域视为卡片/导航而不是正文
REGION_MIN_TEXT_CHARS = 200

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_RE = re.compile(
    r"<meta[^>]+(?:property|name)=[\"'](?:og:)?description[\"'][^>]*>",
    re.IGNORECASE,
)
_META_CONTENT_RE = re.compile(r"content=[\"'](.*?)[\"']", re.IGNORECASE | re.DOTALL)
# strips a trailing " | Site Name" style suffix: separator with whitespace
# on BOTH sides (covers \|·—- and the en dash – some sites use, e.g. an
# HTML-entity-decoded qbitai.com title). A bare hyphen inside a word/number
# (e.g. "GLM-5.2", "GPT-5") is not a title/site-name delimiter and must be
# left alone (real case: the-decoder.com titles with no site suffix at all
# were getting chopped off at the version-number hyphen).
_TITLE_SUFFIX_RE = re.compile(r"\s+[\\|·—–-]\s+[^\\|·—–-]*$")
# some sites glue the site-name suffix directly onto the title with no
# surrounding whitespace at all (real case: 36kr.com "...流体-36氪"). Only
# treat a bare trailing hyphen as this kind of suffix when the tail after it
# is short and space-free - a genuine site name, not a version number like
# "GLM-5.2 in coding..." where real prose continues past the number.
_TITLE_TIGHT_HYPHEN_SUFFIX_RE = re.compile(r"-[^\s\\|·—–-]{1,12}$")


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


def _region_text_length(fragment: str) -> int:
    return len(_TAG_STRIP_RE.sub(" ", fragment).strip())


def _balanced_div_region(html_text: str, open_match: re.Match) -> str:
    """The fragment from a <div …> open tag to ITS matching </div> (depth
    counted), not to the document's last </div> - anything after the
    container (comment widgets, recommendation cards) must stay outside."""
    depth = 1
    for token in _DIV_TOKEN_RE.finditer(html_text, open_match.end()):
        depth += 1 if token.group(0)[1] in "dD" else -1
        if depth == 0:
            return html_text[open_match.start() : token.end()]
    return html_text[open_match.start() :]


def main_content_region(html_text: str) -> str | None:
    """Pick the page region most likely to hold the article body.

    Pages can carry multiple <article> tags where the first is a sidebar
    card (HuggingFace blog), so candidates are ranked by stripped text
    volume instead of document order: substantial <article> first, then
    explicit content-marker divs (blog-content etc., tighter than <main>
    which can also hold comment/recommendation widgets), then <main>,
    then WordPress-style content divs (qbitai has no semantic tags)."""
    soup = BeautifulSoup(html_text, "html.parser")
    for node in soup.select("nav, aside, footer, form, .comments, .related, .recommend, .sharing"):
        node.decompose()

    def pick(selectors: tuple[str, ...]) -> str | None:
        candidates: list[Tag] = []
        for selector in selectors:
            candidates.extend(soup.select(selector))
        substantial = [
            candidate for candidate in candidates
            if len(clean_text(candidate.get_text(" ", strip=True))) >= REGION_MIN_TEXT_CHARS
        ]
        if not substantial:
            return None
        return str(max(substantial, key=lambda value: len(clean_text(value.get_text(" ", strip=True)))))

    # Semantic roots first, then explicit content containers, then broad main.
    # A bare .article is intentionally last: it is a common WordPress fallback,
    # but also a frequent card class.
    for selectors in (
        ("article",),
        (".blog-content", ".entry-content", ".post-content", ".article-content", ".post-body", ".article-body"),
        ("main",),
        (".article",),
    ):
        region = pick(selectors)
        if region:
            return region
    return None


def extract_page_article(html_text: str) -> tuple[str, str]:
    title = ""
    title_match = _TITLE_RE.search(html_text)
    if title_match:
        title = clean_text(html.unescape(title_match.group(1)))
        title = _TITLE_SUFFIX_RE.sub("", title)
        title = _TITLE_TIGHT_HYPHEN_SUFFIX_RE.sub("", title).strip()
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
        if int((cached.get("metadata") or {}).get("content_extraction_version") or 0) != CONTENT_EXTRACTION_VERSION:
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
            extracted = extract_article_content(region, base_url=loc, title=title)
            if not extracted.get("author_detected"):
                byline = extract_page_byline(page_html, base_url=loc)
                if byline:
                    extracted["original_blocks"].insert(0, byline)
                    extracted["author_detected"] = True
            if extracted["original_paragraphs"]:
                metadata.update(
                    {
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

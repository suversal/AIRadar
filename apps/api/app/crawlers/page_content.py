"""Shared full-page article fetching with a local cache.

Used by crawlers whose upstream feed carries little or no body text
(e.g. OpenAI's RSS has no description at all). Extracts the page's
<article>/<main> region into the standard original_* metadata contract.
Article pages are treated as immutable: once cached by canonical URL
hash they are never refetched.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.crawlers.base import canonicalize_url, fetch_url_text, stable_hash
from app.crawlers.sitemap import extract_page_article, main_content_region
from app.crawlers.article_content import extract_article_content
from app.models.domain import RawArticle

DEFAULT_PAGE_CACHE_DIR = Path("data") / "page_cache"


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
    try:
        payload = fetch_page_payload(article.source_url, cache_dir=cache_dir or DEFAULT_PAGE_CACHE_DIR)
    except Exception:
        return
    if not payload:
        return
    article.content = payload["content"]
    article.metadata.update(payload["metadata"])
    article.metadata["content_origin"] = "full_page"


def fetch_page_payload(
    url: str,
    *,
    cache_dir: Path = DEFAULT_PAGE_CACHE_DIR,
) -> dict[str, Any] | None:
    cache_path = Path(cache_dir) / f"{stable_hash(canonicalize_url(url))}.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    page_html = fetch_url_text(url, accept="text/html, */*")
    title, description = extract_page_article(page_html)
    region = main_content_region(page_html)
    extracted = extract_article_content(region, base_url=url) if region else None

    if extracted and extracted["original_paragraphs"]:
        payload = {
            "title": title,
            "content": extracted["original_text"] or description,
            "metadata": {
                "original_paragraphs": extracted["original_paragraphs"],
                "original_images": extracted["original_images"],
                "original_blocks": extracted["original_blocks"],
            },
        }
    elif description and not _is_bare_url(description):
        # no <article>/<main> region (e.g. video/preview pages) but the page
        # still carries a real meta description - better than nothing
        payload = {"title": title, "content": description, "metadata": {}}
    else:
        return None

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # cache is an optimization; never fail the crawl over it
    return payload

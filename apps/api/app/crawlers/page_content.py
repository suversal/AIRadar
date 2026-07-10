"""Shared full-page article fetching with a local cache.

Used by crawlers whose upstream feed carries little or no body text
(e.g. OpenAI's RSS has no description at all). Extracts the page's
<article>/<main> region into the standard original_* metadata contract.
Article pages are treated as immutable: once cached by canonical URL
hash they are never refetched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.crawlers.base import canonicalize_url, fetch_url_text, stable_hash
from app.crawlers.sitemap import extract_page_article, main_content_region
from app.crawlers.article_content import extract_article_content

DEFAULT_PAGE_CACHE_DIR = Path("data") / "page_cache"


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
    elif description:
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

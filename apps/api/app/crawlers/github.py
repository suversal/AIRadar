from __future__ import annotations

import re
import urllib.request
from datetime import datetime, timezone
from html import unescape

from app.crawlers.base import BaseCrawler, clean_text, normalize_article
from app.models.domain import RawArticle, Source

REPO_PATH_RE = re.compile(
    r'href="/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:[?#][^"]*)?"'
)
ARTICLE_RE = re.compile(r"<article\b.*?</article>", re.IGNORECASE | re.DOTALL)
PARAGRAPH_RE = re.compile(r"<p\b[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
SKIP_PATH_OWNERS = {
    "about",
    "collections",
    "customer-stories",
    "enterprise",
    "features",
    "github",
    "login",
    "marketplace",
    "new",
    "orgs",
    "pricing",
    "settings",
    "sponsors",
    "topics",
    "trending",
}


def _strip_html(value: str) -> str:
    return clean_text(re.sub(r"<[^>]+>", " ", unescape(value)))


def _repo_path_from_chunk(chunk: str) -> str:
    match = REPO_PATH_RE.search(chunk)
    if not match:
        return ""
    repo_path = match.group(1)
    owner = repo_path.split("/", 1)[0].lower()
    if owner in SKIP_PATH_OWNERS:
        return ""
    return repo_path


def _description_from_chunk(chunk: str) -> str:
    match = PARAGRAPH_RE.search(chunk)
    if not match:
        return ""
    return _strip_html(match.group(1))


def parse_github_trending(
    html: str,
    source: Source,
    limit: int | None = None,
) -> list[RawArticle]:
    chunks = ARTICLE_RE.findall(html) or [html]
    seen: set[str] = set()
    articles: list[RawArticle] = []
    query_terms = [term.lower() for term in source.config.get("query_terms", [])]
    for chunk in chunks:
        repo_path = _repo_path_from_chunk(chunk)
        if not repo_path or repo_path in seen:
            continue
        seen.add(repo_path)
        description = _description_from_chunk(chunk)
        searchable_text = f"{repo_path} {description}".lower()
        if query_terms and not any(term in searchable_text for term in query_terms):
            continue
        title = repo_path.replace("/", " / ")
        articles.append(
            normalize_article(
                source=source,
                source_url=f"https://github.com/{repo_path}",
                title=f"GitHub Trending: {title}",
                content=description or f"{repo_path} is trending on GitHub.",
                author=repo_path.split("/")[0],
                published_at=datetime.now(timezone.utc),
                language="en",
                raw_score={},
                metadata={"repo": repo_path, "source_type": "github_trending"},
            )
        )
        if limit is not None and len(articles) >= limit:
            break
    return articles


class GitHubTrendingCrawler(BaseCrawler):
    def fetch(self, limit: int | None = None) -> list[RawArticle]:
        request = urllib.request.Request(
            self.source.url,
            headers={"User-Agent": "SuversalAIRadar/0.1"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            html = response.read().decode("utf-8", errors="replace")
        return parse_github_trending(html, self.source, limit=limit)

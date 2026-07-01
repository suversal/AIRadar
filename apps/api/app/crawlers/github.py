from __future__ import annotations

import re
import urllib.request
from datetime import datetime, timezone

from app.crawlers.base import BaseCrawler, normalize_article
from app.models.domain import RawArticle


class GitHubTrendingCrawler(BaseCrawler):
    def fetch(self, limit: int | None = None) -> list[RawArticle]:
        request = urllib.request.Request(
            self.source.url,
            headers={"User-Agent": "SuversalAIRadar/0.1"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            html = response.read().decode("utf-8", errors="replace")
        repo_paths = re.findall(r'href="/([^"/]+/[^"/]+)"', html)
        seen: set[str] = set()
        articles: list[RawArticle] = []
        query_terms = [term.lower() for term in self.source.config.get("query_terms", [])]
        for repo_path in repo_paths:
            if repo_path in seen:
                continue
            seen.add(repo_path)
            title = repo_path.replace("/", " / ")
            if query_terms and not any(term in repo_path.lower() for term in query_terms):
                continue
            articles.append(
                normalize_article(
                    source=self.source,
                    source_url=f"https://github.com/{repo_path}",
                    title=f"GitHub Trending: {title}",
                    content=f"{repo_path} is trending on GitHub.",
                    author=repo_path.split("/")[0],
                    published_at=datetime.now(timezone.utc),
                    language="en",
                    raw_score={},
                    metadata={"repo": repo_path},
                )
            )
            if limit is not None and len(articles) >= limit:
                break
        return articles


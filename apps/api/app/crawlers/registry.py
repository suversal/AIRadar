from __future__ import annotations

from app.crawlers.base import BaseCrawler
from app.crawlers.github import GitHubTrendingCrawler
from app.crawlers.hn import HackerNewsCrawler
from app.crawlers.rss import RSSCrawler
from app.crawlers.sitemap import SitemapCrawler
from app.models.domain import Source


def crawler_for_source(source: Source) -> BaseCrawler:
    if source.type == "hn":
        return HackerNewsCrawler(source)
    if source.type == "github":
        return GitHubTrendingCrawler(source)
    if source.type == "sitemap":
        return SitemapCrawler(source)
    return RSSCrawler(source)


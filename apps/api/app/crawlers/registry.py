from __future__ import annotations

from app.crawlers.attentionvc import AttentionVcCrawler
from app.crawlers.base import BaseCrawler
from app.crawlers.github import GitHubTrendingCrawler
from app.crawlers.hn import HackerNewsCrawler
from app.crawlers.huggingface_papers import HuggingFacePapersCrawler
from app.crawlers.rss import RSSCrawler
from app.crawlers.sitemap import SitemapCrawler
from app.crawlers.telegram_rss import TelegramRSSCrawler
from app.crawlers.v2ex import V2exCrawler
from app.models.domain import Source


def crawler_for_source(source: Source) -> BaseCrawler:
    if source.type == "hn":
        return HackerNewsCrawler(source)
    if source.type == "github":
        return GitHubTrendingCrawler(source)
    if source.type == "sitemap":
        return SitemapCrawler(source)
    if source.type == "huggingface_papers":
        return HuggingFacePapersCrawler(source)
    if source.type == "attentionvc":
        return AttentionVcCrawler(source)
    if source.type == "v2ex":
        return V2exCrawler(source)
    if source.type == "telegram_rss":
        return TelegramRSSCrawler(source)
    return RSSCrawler(source)

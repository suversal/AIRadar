import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.crawlers.run import crawl_sources
from app.models.domain import RawArticle, Source


class FakeCrawler:
    def __init__(self, articles=None, error=None):
        self.articles = articles or []
        self.error = error

    def fetch(self, limit=None):
        if self.error:
            raise self.error
        return self.articles[:limit]


class CrawlRunTests(unittest.TestCase):
    def test_crawl_sources_returns_articles_and_per_source_report(self):
        good_source = Source(
            id="good",
            name="Good Source",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://example.com/feed.xml",
            homepage="https://example.com",
            allowed_domains=["example.com"],
        )
        bad_source = Source(
            id="bad",
            name="Bad Source",
            source_role="context",
            tier="T2",
            type="rss",
            category="media",
            url="https://bad.example/feed.xml",
            homepage="https://bad.example",
            allowed_domains=["bad.example"],
        )
        article = RawArticle(
            id="article-1",
            source_id="good",
            source_name="Good Source",
            source_role="authority",
            source_tier="T1",
            source_url="https://example.com/a",
            title="AI article",
            content="AI content",
            author=None,
            published_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            language="en",
            raw_score={},
            metadata={},
            title_hash="title",
            url_hash="url",
        )

        def crawler_factory(source):
            if source.id == "good":
                return FakeCrawler([article])
            return FakeCrawler(error=RuntimeError("boom"))

        articles, report = crawl_sources(
            [good_source, bad_source],
            limit=10,
            crawler_factory=crawler_factory,
        )

        self.assertEqual(articles, [article])
        self.assertEqual(report["article_count"], 1)
        self.assertEqual(report["source_count"], 2)
        self.assertEqual(report["per_source"]["good"]["status"], "ok")
        self.assertEqual(report["per_source"]["good"]["article_count"], 1)
        self.assertEqual(report["per_source"]["bad"]["status"], "skipped")
        self.assertEqual(report["per_source"]["bad"]["error"], "boom")
        self.assertEqual(report["skipped_reasons"], {"bad:fetch_failed": 1})

    def test_crawl_sources_waits_between_same_domain_sources(self):
        def make_reddit_source(source_id: str, path: str) -> Source:
            return Source(
                id=source_id,
                name=source_id,
                source_role="signal",
                tier="T2",
                type="rss",
                category="community",
                url=f"https://www.reddit.com/{path}/.rss",
                homepage=f"https://www.reddit.com/{path}/",
                allowed_domains=["reddit.com"],
            )

        sources = [
            make_reddit_source("reddit_a", "r/LocalLLaMA"),
            make_reddit_source("reddit_b", "r/MachineLearning"),
        ]
        sleeps: list[float] = []

        with patch("app.crawlers.run.time.sleep", side_effect=sleeps.append):
            crawl_sources(
                sources,
                limit=10,
                crawler_factory=lambda source: FakeCrawler(articles=[]),
            )

        self.assertEqual(len(sleeps), 1)
        self.assertGreater(sleeps[0], 0)

    def test_crawl_sources_does_not_wait_between_different_domains(self):
        def make_source(source_id: str, domain: str) -> Source:
            return Source(
                id=source_id,
                name=source_id,
                source_role="context",
                tier="T2",
                type="rss",
                category="media",
                url=f"https://{domain}/feed.xml",
                homepage=f"https://{domain}",
                allowed_domains=[domain],
            )

        sources = [make_source("a", "one.example"), make_source("b", "two.example")]
        sleeps: list[float] = []

        with patch("app.crawlers.run.time.sleep", side_effect=sleeps.append):
            crawl_sources(
                sources,
                limit=10,
                crawler_factory=lambda source: FakeCrawler(articles=[]),
            )

        self.assertEqual(sleeps, [])


if __name__ == "__main__":
    unittest.main()

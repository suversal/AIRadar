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

    def test_crawl_sources_fetches_different_domains_concurrently(self):
        import threading

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

        # both crawlers must be in-flight at the same time to pass the barrier;
        # a serial implementation deadlocks until the timeout and fails
        barrier = threading.Barrier(2, timeout=5)

        class BarrierCrawler:
            def fetch(self, limit=None):
                barrier.wait()
                return []

        sources = [make_source("a", "one.example"), make_source("b", "two.example")]

        _, report = crawl_sources(
            sources,
            limit=10,
            crawler_factory=lambda source: BarrierCrawler(),
        )

        self.assertEqual(report["per_source"]["a"]["status"], "ok")
        self.assertEqual(report["per_source"]["b"]["status"], "ok")

    def test_crawl_sources_keeps_article_order_deterministic_by_source_order(self):
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

        def make_article(article_id: str, source_id: str) -> RawArticle:
            return RawArticle(
                id=article_id,
                source_id=source_id,
                source_name=source_id,
                source_role="context",
                source_tier="T2",
                source_url=f"https://example.com/{article_id}",
                title=article_id,
                content="AI content",
                author=None,
                published_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
                language="en",
                raw_score={},
                metadata={},
                title_hash=f"t-{article_id}",
                url_hash=f"u-{article_id}",
            )

        import time as time_module

        class SlowFirstCrawler:
            def __init__(self, article, delay):
                self.article = article
                self.delay = delay

            def fetch(self, limit=None):
                time_module.sleep(self.delay)
                return [self.article]

        sources = [make_source("first", "one.example"), make_source("second", "two.example")]
        crawlers = {
            "first": SlowFirstCrawler(make_article("a-first", "first"), 0.2),
            "second": SlowFirstCrawler(make_article("a-second", "second"), 0.0),
        }

        articles, report = crawl_sources(
            sources,
            limit=1,
            crawler_factory=lambda source: crawlers[source.id],
        )

        # the global limit is applied in source order even when a later
        # source finishes first
        self.assertEqual([a.id for a in articles], ["a-first"])
        self.assertEqual(report["per_source"]["first"]["article_count"], 1)
        self.assertEqual(report["per_source"]["second"]["article_count"], 0)

    def test_per_source_crawl_limit_config_overrides_default(self):
        def make_source(source_id: str, domain: str, config=None) -> Source:
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
                config=config or {},
            )

        received: dict[str, int] = {}

        class RecordingCrawler:
            def __init__(self, source_id):
                self.source_id = source_id

            def fetch(self, limit=None):
                received[self.source_id] = limit
                return []

        sources = [
            make_source("boosted", "one.example", {"crawl_limit": 20}),
            make_source("default", "two.example"),
        ]

        crawl_sources(
            sources,
            limit=10,  # default per-source = 10 // 2 = 5
            crawler_factory=lambda source: RecordingCrawler(source.id),
        )

        self.assertEqual(received["boosted"], 20)
        self.assertEqual(received["default"], 5)

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

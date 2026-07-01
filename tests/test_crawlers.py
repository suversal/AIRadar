import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.crawlers.base import normalize_article
from app.crawlers.rss import parse_rss
from app.models.domain import Source


class CrawlerTests(unittest.TestCase):
    def test_normalize_article_removes_tracking_and_hashes_url_and_title(self):
        source = Source(
            id="openai_blog",
            name="OpenAI Blog",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://openai.com/blog/rss.xml",
            homepage="https://openai.com",
            allowed_domains=["openai.com"],
            can_be_main_source=True,
        )

        article = normalize_article(
            source=source,
            source_url="https://openai.com/blog/example?utm_source=x#comments",
            title="  New Agent Model  ",
            content="A useful AI release.",
            author="OpenAI",
            published_at=datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc),
            language="en",
            raw_score={"points": 10},
            metadata={"origin": "fixture"},
        )

        self.assertEqual(article.source_url, "https://openai.com/blog/example")
        self.assertEqual(article.title, "New Agent Model")
        self.assertEqual(len(article.url_hash), 64)
        self.assertEqual(len(article.title_hash), 64)

    def test_parse_rss_returns_normalized_articles(self):
        source = Source(
            id="fixture_rss",
            name="Fixture RSS",
            source_role="context",
            tier="T2",
            type="rss",
            category="media",
            url="https://example.com/rss.xml",
            homepage="https://example.com",
            allowed_domains=["example.com"],
            can_be_main_source=True,
        )
        xml = """<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <title>Fixture</title>
            <item>
              <title>AI system ships</title>
              <link>https://example.com/ai-system?utm_campaign=test</link>
              <description>Important model update.</description>
              <pubDate>Wed, 01 Jul 2026 08:00:00 GMT</pubDate>
              <author>Reporter</author>
            </item>
          </channel>
        </rss>
        """

        articles = parse_rss(xml, source)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "AI system ships")
        self.assertEqual(articles[0].source_url, "https://example.com/ai-system")


if __name__ == "__main__":
    unittest.main()


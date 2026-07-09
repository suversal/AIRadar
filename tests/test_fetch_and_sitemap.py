import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.crawlers.base import fetch_url_text
from app.crawlers.registry import crawler_for_source
from app.crawlers.sitemap import SitemapCrawler, extract_page_article, parse_sitemap_entries
from app.models.domain import Source


class FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


def make_source(**overrides) -> Source:
    payload = {
        "id": "anthropic_news",
        "name": "Anthropic News",
        "source_role": "authority",
        "tier": "T1",
        "type": "sitemap",
        "category": "official",
        "url": "https://www.anthropic.com/sitemap.xml",
        "homepage": "https://www.anthropic.com/news",
        "allowed_domains": ["anthropic.com"],
        "fetch_interval_min": 240,
        "config": {"path_prefix": "https://www.anthropic.com/news/", "max_pages": 5},
    }
    payload.update(overrides)
    return Source(**payload)


SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://www.anthropic.com/careers</loc>
    <lastmod>2026-07-08T00:00:00.000Z</lastmod>
  </url>
  <url>
    <loc>https://www.anthropic.com/news/older-post</loc>
    <lastmod>2026-07-01T10:00:00.000Z</lastmod>
  </url>
  <url>
    <loc>https://www.anthropic.com/news/newer-post</loc>
    <lastmod>2026-07-07T09:30:00.000Z</lastmod>
  </url>
  <url>
    <loc>https://www.anthropic.com/news</loc>
    <lastmod>2026-07-08T00:00:00.000Z</lastmod>
  </url>
</urlset>
"""

PAGE_HTML = """<!DOCTYPE html>
<html>
<head>
<title>Claude ships a new model \\ Anthropic</title>
<meta property="og:description" content="Today we announce a new model." />
</head>
<body><h1>Claude ships a new model</h1></body>
</html>
"""


class FetchUrlTextTests(unittest.TestCase):
    def test_fetch_url_text_retries_rate_limited_requests_with_browser_user_agent(self):
        attempts = []

        def fake_urlopen(request, timeout=20):
            attempts.append(request)
            if len(attempts) == 1:
                raise HTTPError(request.full_url, 429, "Too Many Requests", None, None)
            return FakeResponse(b"<rss></rss>")

        with patch("app.crawlers.base.urllib.request.urlopen", side_effect=fake_urlopen):
            with patch("app.crawlers.base.time.sleep") as fake_sleep:
                text = fetch_url_text("https://example.com/feed")

        self.assertEqual(text, "<rss></rss>")
        self.assertEqual(len(attempts), 2)
        self.assertTrue(fake_sleep.called)
        user_agent = attempts[0].get_header("User-agent")
        self.assertTrue(user_agent.startswith("Mozilla/5.0"))

    def test_fetch_url_text_raises_after_exhausting_retries(self):
        def fake_urlopen(request, timeout=20):
            raise HTTPError(request.full_url, 429, "Too Many Requests", None, None)

        with patch("app.crawlers.base.urllib.request.urlopen", side_effect=fake_urlopen):
            with patch("app.crawlers.base.time.sleep"):
                with self.assertRaises(HTTPError):
                    fetch_url_text("https://example.com/feed", max_attempts=3)

    def test_fetch_url_text_does_not_retry_not_found(self):
        attempts = []

        def fake_urlopen(request, timeout=20):
            attempts.append(request)
            raise HTTPError(request.full_url, 404, "Not Found", None, None)

        with patch("app.crawlers.base.urllib.request.urlopen", side_effect=fake_urlopen):
            with patch("app.crawlers.base.time.sleep"):
                with self.assertRaises(HTTPError):
                    fetch_url_text("https://example.com/feed")

        self.assertEqual(len(attempts), 1)


class SitemapCrawlerTests(unittest.TestCase):
    def test_parse_sitemap_entries_filters_prefix_and_sorts_newest_first(self):
        entries = parse_sitemap_entries(
            SITEMAP_XML, path_prefix="https://www.anthropic.com/news/"
        )

        self.assertEqual(
            [entry[0] for entry in entries],
            [
                "https://www.anthropic.com/news/newer-post",
                "https://www.anthropic.com/news/older-post",
            ],
        )
        self.assertEqual(
            entries[0][1],
            datetime(2026, 7, 7, 9, 30, tzinfo=timezone.utc),
        )

    def test_extract_page_article_reads_title_and_description(self):
        title, description = extract_page_article(PAGE_HTML)

        self.assertEqual(title, "Claude ships a new model")
        self.assertEqual(description, "Today we announce a new model.")

    def test_sitemap_crawler_fetch_builds_normalized_articles(self):
        def fake_fetch(url, **kwargs):
            if url.endswith("sitemap.xml"):
                return SITEMAP_XML
            return PAGE_HTML

        source = make_source()
        crawler = SitemapCrawler(source)
        with patch("app.crawlers.sitemap.fetch_url_text", side_effect=fake_fetch):
            articles = crawler.fetch(limit=10)

        self.assertEqual(len(articles), 2)
        first = articles[0]
        self.assertEqual(first.source_id, "anthropic_news")
        self.assertEqual(first.title, "Claude ships a new model")
        self.assertEqual(first.source_url, "https://www.anthropic.com/news/newer-post")
        self.assertEqual(first.content, "Today we announce a new model.")
        self.assertEqual(
            first.published_at, datetime(2026, 7, 7, 9, 30, tzinfo=timezone.utc)
        )

    def test_sitemap_crawler_respects_max_pages_config(self):
        def fake_fetch(url, **kwargs):
            if url.endswith("sitemap.xml"):
                return SITEMAP_XML
            return PAGE_HTML

        source = make_source(config={"path_prefix": "https://www.anthropic.com/news/", "max_pages": 1})
        crawler = SitemapCrawler(source)
        with patch("app.crawlers.sitemap.fetch_url_text", side_effect=fake_fetch):
            articles = crawler.fetch(limit=10)

        self.assertEqual(len(articles), 1)

    def test_registry_returns_sitemap_crawler_for_sitemap_type(self):
        crawler = crawler_for_source(make_source())

        self.assertIsInstance(crawler, SitemapCrawler)


if __name__ == "__main__":
    unittest.main()

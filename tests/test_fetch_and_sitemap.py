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
<body>
<nav><ul><li>Home</li><li>Careers</li></ul></nav>
<article>
<h1>Claude ships a new model</h1>
<p>Today we announce a new model with stronger reasoning.</p>
<p>The model is available to all developers starting today.</p>
<img src="/images/model-card.png" alt="Model card" />
</article>
<footer><p>Copyright Anthropic</p></footer>
</body>
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

    def test_fetch_url_text_defaults_to_ten_second_timeout(self):
        captured: dict = {}

        def fake_urlopen(request, timeout=None):
            captured["timeout"] = timeout
            return FakeResponse(b"<rss></rss>")

        with patch("app.crawlers.base.urllib.request.urlopen", side_effect=fake_urlopen):
            fetch_url_text("https://example.com/feed")

        self.assertEqual(captured["timeout"], 10)

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

    def setUp(self):
        import tempfile

        self._cache_tmp = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self._cache_tmp.name)
        self.addCleanup(self._cache_tmp.cleanup)

    def test_sitemap_crawler_fetch_builds_normalized_articles(self):
        def fake_fetch(url, **kwargs):
            if url.endswith("sitemap.xml"):
                return SITEMAP_XML
            return PAGE_HTML

        source = make_source()
        crawler = SitemapCrawler(source, cache_dir=self.cache_dir)
        with patch("app.crawlers.sitemap.fetch_url_text", side_effect=fake_fetch):
            articles = crawler.fetch(limit=10)

        self.assertEqual(len(articles), 2)
        first = articles[0]
        self.assertEqual(first.source_id, "anthropic_news")
        self.assertEqual(first.title, "Claude ships a new model")
        self.assertEqual(first.source_url, "https://www.anthropic.com/news/newer-post")
        self.assertIn("Today we announce a new model", first.content)
        self.assertEqual(
            first.published_at, datetime(2026, 7, 7, 9, 30, tzinfo=timezone.utc)
        )

    def test_sitemap_crawler_extracts_full_article_body_from_article_region(self):
        def fake_fetch(url, **kwargs):
            if url.endswith("sitemap.xml"):
                return SITEMAP_XML
            return PAGE_HTML

        crawler = SitemapCrawler(make_source(), cache_dir=self.cache_dir)
        with patch("app.crawlers.sitemap.fetch_url_text", side_effect=fake_fetch):
            articles = crawler.fetch(limit=10)

        first = articles[0]
        self.assertIn("stronger reasoning", first.content)
        self.assertIn("available to all developers", first.content)
        self.assertNotIn("Careers", first.content)
        self.assertNotIn("Copyright", first.content)
        paragraphs = first.metadata["original_paragraphs"]
        self.assertEqual(len(paragraphs), 3)  # h1 + two paragraphs
        images = first.metadata["original_images"]
        self.assertEqual(
            images[0]["url"],
            "https://www.anthropic.com/images/model-card.png",
        )
        self.assertTrue(
            any(block["type"] == "image" for block in first.metadata["original_blocks"])
        )

    def test_sitemap_crawler_falls_back_to_description_without_article_region(self):
        bare_html = (
            "<html><head><title>Bare page</title>"
            '<meta name="description" content="Only a description." />'
            "</head><body><p>junk nav</p></body></html>"
        )

        def fake_fetch(url, **kwargs):
            if url.endswith("sitemap.xml"):
                return SITEMAP_XML
            return bare_html

        crawler = SitemapCrawler(make_source(), cache_dir=self.cache_dir)
        with patch("app.crawlers.sitemap.fetch_url_text", side_effect=fake_fetch):
            articles = crawler.fetch(limit=10)

        first = articles[0]
        self.assertEqual(first.content, "Only a description.")
        self.assertEqual(first.metadata.get("original_paragraphs") or [], [])

    def test_sitemap_crawler_respects_max_pages_config(self):
        def fake_fetch(url, **kwargs):
            if url.endswith("sitemap.xml"):
                return SITEMAP_XML
            return PAGE_HTML

        source = make_source(config={"path_prefix": "https://www.anthropic.com/news/", "max_pages": 1})
        crawler = SitemapCrawler(source, cache_dir=self.cache_dir)
        with patch("app.crawlers.sitemap.fetch_url_text", side_effect=fake_fetch):
            articles = crawler.fetch(limit=10)

        self.assertEqual(len(articles), 1)

    def test_sitemap_crawler_serves_unchanged_pages_from_cache(self):
        import tempfile

        fetch_calls: list[str] = []

        def fake_fetch(url, **kwargs):
            fetch_calls.append(url)
            if url.endswith("sitemap.xml"):
                return SITEMAP_XML
            return PAGE_HTML

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            source = make_source()

            with patch("app.crawlers.sitemap.fetch_url_text", side_effect=fake_fetch):
                first = SitemapCrawler(source, cache_dir=cache_dir).fetch(limit=10)
            first_call_count = len(fetch_calls)

            with patch("app.crawlers.sitemap.fetch_url_text", side_effect=fake_fetch):
                second = SitemapCrawler(source, cache_dir=cache_dir).fetch(limit=10)

        # second run refetches only the sitemap; both pages come from cache
        self.assertEqual(first_call_count, 3)  # sitemap + 2 pages
        self.assertEqual(len(fetch_calls) - first_call_count, 1)
        self.assertEqual(len(second), len(first))
        self.assertEqual(
            [a.source_url for a in second], [a.source_url for a in first]
        )
        self.assertEqual(second[0].title, first[0].title)
        self.assertEqual(
            second[0].metadata.get("original_paragraphs"),
            first[0].metadata.get("original_paragraphs"),
        )
        self.assertEqual(second[0].published_at, first[0].published_at)

    def test_sitemap_crawler_refetches_when_lastmod_changes(self):
        import tempfile

        fetch_calls: list[str] = []
        current_sitemap = {"xml": SITEMAP_XML}

        def fake_fetch(url, **kwargs):
            fetch_calls.append(url)
            if url.endswith("sitemap.xml"):
                return current_sitemap["xml"]
            return PAGE_HTML

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            source = make_source()

            with patch("app.crawlers.sitemap.fetch_url_text", side_effect=fake_fetch):
                SitemapCrawler(source, cache_dir=cache_dir).fetch(limit=10)

            current_sitemap["xml"] = SITEMAP_XML.replace(
                "2026-07-07T09:30:00.000Z", "2026-07-09T00:00:00.000Z"
            )
            fetch_calls.clear()
            with patch("app.crawlers.sitemap.fetch_url_text", side_effect=fake_fetch):
                articles = SitemapCrawler(source, cache_dir=cache_dir).fetch(limit=10)

        # updated page refetched, unchanged page still cached
        self.assertEqual(len(fetch_calls), 2)  # sitemap + 1 updated page
        self.assertEqual(len(articles), 2)

    def test_registry_returns_sitemap_crawler_for_sitemap_type(self):
        crawler = crawler_for_source(make_source())

        self.assertIsInstance(crawler, SitemapCrawler)


if __name__ == "__main__":
    unittest.main()

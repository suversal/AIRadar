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
<p>It improves coding, analysis, and long-context comprehension across the board,
while keeping latency comparable to the previous generation. Early testers report
meaningfully better results on agentic workflows and multi-step tool use.</p>
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
        # cloudflare blocks requests carrying crawler markers or missing
        # fetch-metadata headers (openai.com returned 403)
        self.assertNotIn("Radar", user_agent)
        self.assertEqual(attempts[0].get_header("Sec-fetch-mode"), "navigate")
        self.assertIsNotNone(attempts[0].get_header("Accept-language"))

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


class PageContentTests(unittest.TestCase):
    def test_fetch_page_payload_extracts_and_caches(self):
        import tempfile

        from app.crawlers.page_content import fetch_page_payload

        calls: list[str] = []

        def fake_fetch(url, **kwargs):
            calls.append(url)
            return PAGE_HTML

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            with patch("app.crawlers.page_content.fetch_url_text", side_effect=fake_fetch):
                first = fetch_page_payload("https://www.anthropic.com/news/newer-post", cache_dir=cache_dir)
                second = fetch_page_payload("https://www.anthropic.com/news/newer-post", cache_dir=cache_dir)

        self.assertEqual(len(calls), 1)  # second call served from cache
        self.assertEqual(first["title"], "Claude ships a new model")
        self.assertIn("stronger reasoning", first["content"])
        self.assertEqual(second["content"], first["content"])
        self.assertTrue(first["metadata"]["original_paragraphs"])

    def test_fetch_page_payload_returns_none_without_main_region(self):
        import tempfile

        from app.crawlers.page_content import fetch_page_payload

        bare = "<html><head><title>t</title></head><body><p>nav junk</p></body></html>"
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.crawlers.page_content.fetch_url_text", return_value=bare):
                payload = fetch_page_payload("https://x.example/post", cache_dir=Path(tmpdir))

        self.assertIsNone(payload)

    def test_main_content_region_skips_short_sidebar_article_for_main(self):
        # HuggingFace 博客页有多个 <article>：第一个是侧栏模型卡片（几十字），
        # 真正文在 <main> 里。region 选择必须看文本量，不能盲取第一个 article。
        from app.crawlers.sitemap import main_content_region

        body = "正文段落。" * 100
        page = (
            "<html><body>"
            "<article><div>model-card/tiny-link Updated 4 days ago</div></article>"
            f"<main><h1>标题</h1><p>{body}</p></main>"
            "</body></html>"
        )

        region = main_content_region(page)

        self.assertIsNotNone(region)
        self.assertIn("正文段落。", region)

    def test_main_content_region_still_prefers_substantial_article_over_main(self):
        from app.crawlers.sitemap import main_content_region

        body = "article body text. " * 30
        page = (
            "<html><body><main><nav>site nav junk</nav>"
            f"<article><p>{body}</p></article>"
            "<footer>footer junk</footer></main></body></html>"
        )

        region = main_content_region(page)

        self.assertTrue(region.startswith("<article"))
        self.assertNotIn("footer junk", region)

    def test_main_content_region_falls_back_to_wordpress_article_div(self):
        # qbitai（WordPress 主题）没有 <article>/<main>，正文在 <div class="article">。
        from app.crawlers.sitemap import main_content_region

        body = "量子位正文内容。" * 60
        page = (
            "<html><body><div class=\"content\">"
            f"<div class=\"article\"><h1>标题</h1><p>{body}</p></div>"
            "<div class=\"content_right\">sidebar</div>"
            "</div></body></html>"
        )

        region = main_content_region(page)

        self.assertIsNotNone(region)
        self.assertIn("量子位正文内容。", region)

    def test_fetch_page_payload_falls_back_to_meta_description_without_main_region(self):
        # video/preview pages (e.g. infoq.cn/video/...) have no <article>/<main>
        # wrapper at all, but do carry a real meta description worth keeping
        # instead of silently giving up and leaving the RSS's thin summary.
        import tempfile

        from app.crawlers.page_content import fetch_page_payload

        video_page = (
            "<html><head><title>预告：Agent 重新定义可观测性</title>"
            '<meta name="description" content="Agent 正在重新定义可观测性的边界。">'
            "</head><body><p>player nav junk</p></body></html>"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.crawlers.page_content.fetch_url_text", return_value=video_page):
                payload = fetch_page_payload("https://x.example/video/1", cache_dir=Path(tmpdir))

        self.assertIsNotNone(payload)
        self.assertEqual(payload["content"], "Agent 正在重新定义可观测性的边界。")


class RSSFullContentTests(unittest.TestCase):
    FEED = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>OpenAI</title>
<item>
  <title>GPT-6 ships</title>
  <link>https://openai.com/index/gpt-6</link>
  <pubDate>Thu, 09 Jul 2026 13:00:00 GMT</pubDate>
</item>
</channel></rss>
"""

    def test_rss_crawler_fetches_full_page_for_thin_items_when_configured(self):
        import tempfile

        from app.crawlers.rss import RSSCrawler
        from app.models.domain import Source

        source = Source(
            id="openai_blog",
            name="OpenAI Blog",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://openai.com/news/rss.xml",
            homepage="https://openai.com/news/",
            allowed_domains=["openai.com"],
            config={"fetch_full_content": True},
        )

        def fake_fetch(url, **kwargs):
            if url.endswith("rss.xml"):
                return self.FEED
            return PAGE_HTML

        with tempfile.TemporaryDirectory() as tmpdir:
            crawler = RSSCrawler(source, page_cache_dir=Path(tmpdir))
            with patch("app.crawlers.rss.fetch_url_text", side_effect=fake_fetch), patch(
                "app.crawlers.page_content.fetch_url_text", side_effect=fake_fetch
            ):
                articles = crawler.fetch(limit=5)

        article = articles[0]
        self.assertIn("stronger reasoning", article.content)
        self.assertTrue(article.metadata.get("original_paragraphs"))
        self.assertEqual(article.metadata.get("content_origin"), "full_page")

    def test_rss_crawler_keeps_feed_content_without_config(self):
        import tempfile

        from app.crawlers.rss import RSSCrawler
        from app.models.domain import Source

        source = Source(
            id="openai_blog",
            name="OpenAI Blog",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://openai.com/news/rss.xml",
            homepage="https://openai.com/news/",
            allowed_domains=["openai.com"],
        )

        fetch_calls: list[str] = []

        def fake_fetch(url, **kwargs):
            fetch_calls.append(url)
            return self.FEED

        with tempfile.TemporaryDirectory() as tmpdir:
            crawler = RSSCrawler(source, page_cache_dir=Path(tmpdir))
            with patch("app.crawlers.rss.fetch_url_text", side_effect=fake_fetch):
                articles = crawler.fetch(limit=5)

        self.assertEqual(len(fetch_calls), 1)  # feed only, no page fetches
        self.assertEqual(articles[0].metadata.get("content_origin"), None)


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
        self.assertEqual(len(paragraphs), 4)  # h1 + three paragraphs
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

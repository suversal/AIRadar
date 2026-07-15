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

    def test_fetch_url_text_follows_308_permanent_redirect(self):
        # 真实案例：google_ai_blog 全文抓取撞上 308 Permanent Redirect —
        # Python 标准库的 HTTPRedirectHandler 不处理 301/302/303/307，
        # 直接抛出 HTTPError 而不是跟随跳转。
        import email.message

        attempts = []

        def fake_urlopen(request, timeout=20):
            attempts.append(request.full_url)
            if request.full_url == "https://blog.google/old-path":
                headers = email.message.Message()
                headers["Location"] = "https://blog.google/new-path"
                raise HTTPError(request.full_url, 308, "Permanent Redirect", headers, None)
            return FakeResponse(b"<html>real content</html>")

        with patch("app.crawlers.base.urllib.request.urlopen", side_effect=fake_urlopen):
            text = fetch_url_text("https://blog.google/old-path")

        self.assertEqual(text, "<html>real content</html>")
        self.assertEqual(attempts, ["https://blog.google/old-path", "https://blog.google/new-path"])

    def test_fetch_url_text_retries_transient_network_errors(self):
        # microsoft_research 的 RSS 请求撞上过 SSL 握手超时
        # (urllib.error.URLError)，这类瞬时网络错误之前完全不重试。
        from socket import timeout as socket_timeout
        from urllib.error import URLError

        attempts = []

        def fake_urlopen(request, timeout=20):
            attempts.append(request)
            if len(attempts) == 1:
                raise URLError(socket_timeout("The handshake operation timed out"))
            return FakeResponse(b"<rss>ok</rss>")

        with patch("app.crawlers.base.urllib.request.urlopen", side_effect=fake_urlopen):
            with patch("app.crawlers.base.time.sleep") as fake_sleep:
                text = fetch_url_text("https://www.microsoft.com/en-us/research/feed/")

        self.assertEqual(text, "<rss>ok</rss>")
        self.assertEqual(len(attempts), 2)
        self.assertTrue(fake_sleep.called)

    def test_fetch_url_text_raises_after_exhausting_network_error_retries(self):
        from socket import timeout as socket_timeout
        from urllib.error import URLError

        def fake_urlopen(request, timeout=20):
            raise URLError(socket_timeout("timed out"))

        with patch("app.crawlers.base.urllib.request.urlopen", side_effect=fake_urlopen):
            with patch("app.crawlers.base.time.sleep"):
                with self.assertRaises(URLError):
                    fetch_url_text("https://example.com/feed", max_attempts=3)


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

    def test_ithome_profile_extracts_full_body_and_invalidates_meta_fallback_cache(self):
        import json
        import tempfile

        from app.crawlers.base import canonicalize_url, stable_hash
        from app.crawlers.page_content import fetch_page_payload

        url = "https://www.ithome.com/0/977/074.htm"
        page = """
        <html><head><title>Meta 高管预测 - IT之家</title>
        <meta name="description" content="只有一小段摘要"></head><body>
          <div class="info clearfix">
            <span id="pubtime_baidu">2026/7/15 15:54:02</span>
            <span id="source_baidu">来源：<a href="https://www.ithome.com/">IT之家</a></span>
            <span id="author_baidu">作者：<strong>远洋</strong></span>
          </div>
          <div id="paragraph" class="post_content">
            <p>第一段完整正文。这里补充足够多的文本用于模拟 IT之家真实文章正文容器。</p>
            <p>第二段完整正文。Meta 正在重新评估企业内部人工智能 Token 的预算与资源分配方式。</p>
            <p>第三段完整正文。未来工程师的使用额度可能根据投入产出和业务价值进行调整。</p>
            <p>第四段完整正文。模型服务价格仍可能随着供应商竞争以及推理效率提升而逐步下降。</p>
            <p>第五段完整正文。企业需要像管理 GPU、CPU、存储空间和运营费用一样管理模型计算预算。</p>
            <p>第六段完整正文。单纯消耗大量人工智能资源并不意味着能够为产品和业务创造实际价值。</p>
            <p><img src="//img.ithome.com/images/v2/t.png"
              data-original="/newsuploadfiles/2026/7/real-image.png" width="972" height="529"></p>
            <p class="ad-tips">广告声明：文内链接仅供参考，IT之家所有文章均包含本声明。</p>
          </div>
        </body></html>
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / f"{stable_hash(canonicalize_url(url))}.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "content": "只有一小段摘要",
                        "metadata": {
                            "content_extraction_version": 2,
                            "content_profile": "meta-description-v2",
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch("app.crawlers.page_content.fetch_url_text", return_value=page) as fetch:
                payload = fetch_page_payload(url, cache_dir=Path(tmpdir))

        fetch.assert_called_once()
        self.assertEqual(payload["metadata"]["content_profile"], "ithome-v2")
        self.assertEqual(len(payload["metadata"]["original_paragraphs"]), 6)
        self.assertNotIn("广告声明", payload["metadata"]["original_text"])
        self.assertEqual(payload["metadata"]["original_blocks"][0]["type"], "byline")
        self.assertEqual(payload["metadata"]["original_blocks"][0]["author"]["name"], "远洋")
        self.assertEqual(
            payload["metadata"]["original_images"][0]["url"],
            "https://www.ithome.com/newsuploadfiles/2026/7/real-image.png",
        )

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

    def test_main_content_region_ignores_article_cards_inside_aside_sidebar(self):
        # 真实案例（Northwestern 新闻页）：真正文没有包在 <article> 里，只在
        # <main> 的普通 <p> 段落里；反倒是 <aside> 里的"相关文章"卡片各自
        # 包在 <article class="feature-box"> 里，且拼起来字数比正文还多，
        # 纯按文本量选 region 会错误地把不相关的推荐卡片当成正文。
        from app.crawlers.sitemap import main_content_region

        real_body = "The cerebellum-inspired device ignores expected inputs. " * 10
        page = (
            "<html><body><div id=\"page\"><main class=\"content\">"
            "<h1>AI Gets a Cerebellum</h1>"
            "<article class=\"feature-box\"><p>The Problem: short summary card.</p></article>"
            f"<section class=\"news-wysiwyg\"><p>{real_body}</p></section>"
            "</main>"
            "<aside class=\"recent-news\">"
            + "".join(
                f'<article class="feature-box"><h4>Recent article number {i}</h4>'
                f"<p>Recent article number {i} teaser text repeated for length several times over "
                f"so this single sidebar card alone exceeds the substantial-region character "
                f"threshold, same as the real Northwestern page that exposed this bug.</p></article>"
                for i in range(5)
            )
            + "</aside></div></body></html>"
        )

        region = main_content_region(page)

        self.assertIsNotNone(region)
        self.assertIn("cerebellum-inspired device", region)
        self.assertNotIn("Recent article number", region)

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

    def test_fetch_page_payload_rejects_bare_url_meta_description(self):
        # real case: a tweet whose only "content" is a shortened media link -
        # og:description is literally just that URL. A bare URL string as
        # "article body" is actively misleading, worse than falling back to
        # the page title, so this must not be treated as usable content.
        import tempfile

        from app.crawlers.page_content import fetch_page_payload

        tweet_page = (
            '<html><head><title>Someone on X</title>'
            '<meta property="og:description" content="https://t.co/2QaxouWxxm">'
            "</head><body><p>nav junk</p></body></html>"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.crawlers.page_content.fetch_url_text", return_value=tweet_page):
                payload = fetch_page_payload("https://twitter.com/x/status/1", cache_dir=Path(tmpdir))

        self.assertIsNone(payload)


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

    def test_rss_crawler_defers_body_fetch_to_pipeline(self):
        # 流程重排(2026-07-12 晚):fetch() 只拉 feed 元数据,绝不逐篇抓
        # 原文页——正文拉取延迟到预筛通过之后,由 pipeline 执行
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

        def fail_page_fetch(url, **kwargs):
            raise AssertionError("fetch() must not pull article pages any more")

        def fake_feed_fetch(url, **kwargs):
            return self.FEED

        with tempfile.TemporaryDirectory() as tmpdir:
            crawler = RSSCrawler(source, page_cache_dir=Path(tmpdir))
            with patch("app.crawlers.rss.fetch_url_text", side_effect=fake_feed_fetch), patch(
                "app.crawlers.page_content.fetch_url_text", side_effect=fail_page_fetch
            ):
                articles = crawler.fetch(limit=5)

        article = articles[0]
        self.assertEqual(article.metadata.get("body_fetch"), "deferred")
        self.assertIsNone(article.metadata.get("content_origin"))
        self.assertNotIn("stronger reasoning", article.content)

    def test_rss_crawler_feed_only_sources_are_not_marked_deferred(self):
        # use_feed_content_only 的源(feed 自带全文)永远不需要二次拉正文
        import tempfile

        from app.crawlers.rss import RSSCrawler
        from app.models.domain import Source

        source = Source(
            id="ithome",
            name="IT之家",
            source_role="context",
            tier="T2",
            type="rss",
            category="media",
            url="https://www.ithome.com/rss/",
            homepage="https://www.ithome.com",
            allowed_domains=["ithome.com"],
            config={"use_feed_content_only": True},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            crawler = RSSCrawler(source, page_cache_dir=Path(tmpdir))
            with patch(
                "app.crawlers.rss.fetch_url_text", side_effect=lambda url, **kwargs: self.FEED
            ):
                articles = crawler.fetch(limit=5)

        self.assertIsNone(articles[0].metadata.get("body_fetch"))


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

    def test_extract_page_article_keeps_mid_title_hyphen_without_site_suffix(self):
        # 真实案例（the-decoder.com）：<title> 本身就是纯标题、没有" - 站点名"
        # 后缀，但标题里含产品版本号连字符"GLM-5.2"——旧正则把它误判成
        # 分隔符，从那个连字符开始把标题腰斩，导致后续标题去重比对失败
        html = (
            "<html><head>"
            "<title>Meta's Muse Spark 1.1 outperforms GLM-5.2 in coding and costs slightly less</title>"
            "</head><body></body></html>"
        )

        title, _ = extract_page_article(html)

        self.assertEqual(
            title,
            "Meta's Muse Spark 1.1 outperforms GLM-5.2 in coding and costs slightly less",
        )

    def test_extract_page_article_still_strips_real_site_name_suffix(self):
        # 真正的"标题 - 站点名"后缀（分隔符两侧都有空格）必须继续正确剥离
        html = "<html><head><title>Some Headline - The Decoder</title></head><body></body></html>"

        title, _ = extract_page_article(html)

        self.assertEqual(title, "Some Headline")

    def test_extract_page_article_strips_en_dash_site_suffix(self):
        # 真实案例（qbitai.com）：站点名后缀用的是 en dash "–"（U+2013，
        # HTML 实体 &#8211;），不在旧字符类 [\|·—-] 里，导致后缀没被剥离
        html = (
            "<html><head><title>中国首个十万卡集群落成！全国产算力支撑"
            "“十万卡时代” &#8211; 量子位</title></head><body></body></html>"
        )

        title, _ = extract_page_article(html)

        self.assertEqual(title, "中国首个十万卡集群落成！全国产算力支撑“十万卡时代”")

    def test_extract_page_article_strips_tight_hyphen_site_suffix_at_end(self):
        # 真实案例（36kr.com）：站点名紧贴在连字符后、两侧都没有空格
        # （"...流体-36氪"），必须和真正的版本号连字符（GLM-5.2）区分——
        # 判据是连字符后到字符串末尾这段"尾巴"很短且不含空白
        html = (
            "<html><head><title>36氪首发 | 三个月融三轮，上交大00后博士让"
            "具身智能仿生扑翼机器人理解并驾驭流体-36氪</title></head><body></body></html>"
        )

        title, _ = extract_page_article(html)

        self.assertEqual(
            title,
            "36氪首发 | 三个月融三轮，上交大00后博士让具身智能仿生扑翼机器人理解并驾驭流体",
        )

    def test_extract_page_article_keeps_mid_title_hyphen_with_long_tail(self):
        # 回归防护：连字符后尾巴较长（真实正文续写，不是站点名）时依然不剥离
        html = (
            "<html><head><title>Meta's Muse Spark 1.1 outperforms GLM-5.2 "
            "in coding and costs slightly less</title></head><body></body></html>"
        )

        title, _ = extract_page_article(html)

        self.assertEqual(
            title,
            "Meta's Muse Spark 1.1 outperforms GLM-5.2 in coding and costs slightly less",
        )

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
        # the <h1> duplicates the page title and must be dropped, not kept
        # as the article's own first paragraph (regression, see
        # test_extract_article_content_drops_leading_block_that_duplicates_title)
        self.assertEqual(len(paragraphs), 3)
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

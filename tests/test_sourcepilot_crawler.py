import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.crawlers.registry import crawler_for_source
from app.crawlers.sourcepilot import SourcePilotCrawler, parse_sourcepilot_items
from app.models.domain import Source


def make_source(**config_overrides) -> Source:
    config = {
        "sp_platform": "智谱",
        "sp_source_type": "wechat",
        "same_domain_delay_seconds": 0,
        "sp_article_limit": 20,
        "recent_days": 0,
        **config_overrides,
    }
    return Source(
        id="sp_wechat_zhipu",
        name="公众号 · 智谱",
        source_role="authority",
        tier="T1",
        type="sourcepilot",
        category="official",
        url="http://127.0.0.1:8420/api/v1/wechat/feed?account=%E6%99%BA%E8%B0%B1",
        homepage="https://mp.weixin.qq.com",
        allowed_domains=["mp.weixin.qq.com"],
        language="zh",
        config=config,
    )


def make_item(**overrides) -> dict:
    item = {
        "id": "wechat:123",
        "source": {"type": "wechat", "name": "公众号 · 智谱", "platform": "智谱"},
        "title": "GLM-5 发布",
        "summary": "新一代旗舰模型",
        "url": "https://mp.weixin.qq.com/s/abc123",
        "author": "智谱",
        "published_at": "2026-08-01T10:00:00Z",
        "discovered_at": "2026-08-01T10:30:00Z",
        "time_basis": "published",
        "score": 0.0,
        "categories": ["model"],
        "lang": "zh",
        "media": [],
        "raw": {"do": "not-depend-on-me"},
    }
    item.update(overrides)
    return item


def make_envelope(
    items=None,
    *,
    ok=True,
    next_cursor=None,
    has_more=False,
    version="1.8.0",
    error=None,
):
    return json.dumps(
        {
            "ok": ok,
            "data": {"items": items or []} if ok else None,
            "meta": {
                "contract_version": version,
                "next_cursor": next_cursor,
                "has_more": has_more,
            },
            "error": error,
        }
    )


def extracted_article(text="正文第一段", *, blocks=None) -> dict:
    """`fetch_manual_article()` 的返回形状（草稿管理同款）。"""
    return {
        "canonical_url": "https://mp.weixin.qq.com/s/abc123",
        "title": "GLM-5 发布",
        "author": "作者行",
        "language": "zh",
        "content": text,
        "original_blocks": blocks
        or [
            {"type": "paragraph", "text": text},
            {"type": "heading", "text": "小标题"},
            {"type": "image", "url": "https://mmbiz.qpic.cn/x.png"},
        ],
        "original_paragraphs": [text],
        "original_images": ["https://mmbiz.qpic.cn/x.png"],
        "content_origin": "manual_url_fetch",
    }


class CrawlerHarness:
    """在 tempdir 里组一个可 fetch 的 crawler。

    列表走 HTTP（patch fetch_url_text），正文走 AIRADAR 自己的提取器
    （patch fetch_manual_article）——这正是这次改动的重点：正文不再绕 SourcePilot。
    """

    def __init__(self, source: Source, tmpdir: str):
        self.cache_dir = Path(tmpdir) / "article_cache"
        self.crawler = SourcePilotCrawler(source, article_cache_dir=self.cache_dir)
        self.requests: list[str] = []
        self.items_responses: list[str] = []
        self.extract_calls: list[str] = []
        self.extracted: dict | None = extracted_article()
        self.extract_error: Exception | None = None

    def fake_fetch(self, url, **kwargs):
        self.requests.append(url)
        return self.items_responses.pop(0)

    def fake_extract(self, url, **kwargs):
        self.extract_calls.append(url)
        if self.extract_error:
            raise self.extract_error
        return self.extracted


class ParseTests(unittest.TestCase):
    def test_field_mapping(self):
        articles = parse_sourcepilot_items([make_item()], make_source())
        self.assertEqual(len(articles), 1)
        article = articles[0]
        self.assertEqual(article.title, "GLM-5 发布")
        self.assertEqual(article.content, "新一代旗舰模型")
        self.assertEqual(article.author, "智谱")
        self.assertEqual(article.language, "zh")
        self.assertEqual(
            article.published_at, datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
        )
        self.assertEqual(article.raw_score, {"sp_score": 0.0})
        self.assertEqual(article.metadata["sp_item_id"], "wechat:123")
        self.assertEqual(article.metadata["time_basis"], "published")
        self.assertEqual(article.metadata["categories"], ["model"])
        self.assertFalse(article.metadata["rss_pubdate_missing"])
        self.assertEqual(article.metadata["content_origin"], "sourcepilot_summary")
        # 契约红线:raw 不进任何逻辑
        self.assertNotIn("raw", article.metadata)

    def test_empty_summary_falls_back_to_title(self):
        articles = parse_sourcepilot_items(
            [make_item(summary=None)], make_source()
        )
        self.assertEqual(articles[0].content, "GLM-5 发布")

    def test_null_published_at_backfills_and_flags(self):
        articles = parse_sourcepilot_items(
            [make_item(published_at=None, time_basis="discovered")], make_source()
        )
        article = articles[0]
        # normalize 回填 now() 是 AIRADAR 既有行为;真实依据在 metadata
        self.assertIsNotNone(article.published_at)
        self.assertTrue(article.metadata["rss_pubdate_missing"])
        self.assertEqual(article.metadata["time_basis"], "discovered")

    def test_missing_title_or_url_skipped(self):
        articles = parse_sourcepilot_items(
            [make_item(title=""), make_item(url="")], make_source()
        )
        self.assertEqual(articles, [])

    def test_recent_days_prunes_old_items_before_enrich(self):
        now = datetime.now(timezone.utc)
        recent = make_item(
            url="https://mp.weixin.qq.com/s/new",
            published_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        old = make_item(
            url="https://mp.weixin.qq.com/s/old",
            published_at=(now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        undated = make_item(url="https://mp.weixin.qq.com/s/undated", published_at=None)
        source = make_source(recent_days=7)
        articles = parse_sourcepilot_items([recent, old, undated], source)
        urls = [a.source_url for a in articles]
        self.assertIn("https://mp.weixin.qq.com/s/new", urls)
        self.assertNotIn("https://mp.weixin.qq.com/s/old", urls)
        # published_at 为 null 的保留,与 pipeline 的过滤语义一致
        self.assertIn("https://mp.weixin.qq.com/s/undated", urls)

    def test_recent_days_zero_keeps_everything(self):
        old = make_item(published_at="2020-01-01T00:00:00Z")
        articles = parse_sourcepilot_items([old], make_source(recent_days=0))
        self.assertEqual(len(articles), 1)


class FetchTests(unittest.TestCase):
    def _run(self, harness: CrawlerHarness, limit=None):
        with patch(
            "app.crawlers.sourcepilot.fetch_url_text",
            side_effect=harness.fake_fetch,
        ), patch(
            "app.services.manual_article_fetcher.fetch_manual_article",
            side_effect=harness.fake_extract,
        ):
            return harness.crawler.fetch(limit=limit)

    def test_fetch_parses_and_enriches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            harness = CrawlerHarness(make_source(), tmpdir)
            harness.items_responses = [make_envelope([make_item()])]
            harness.extracted = extracted_article("完整正文正文正文")
            articles = self._run(harness)
            self.assertEqual(len(articles), 1)
            article = articles[0]
            self.assertEqual(article.content, "完整正文正文正文")
            # 富文本走 original_blocks —— 它已在事件 metadata 白名单里,
            # 前端原生渲染,展示侧零改动
            blocks = article.metadata["original_blocks"]
            self.assertEqual(
                {b["type"] for b in blocks}, {"paragraph", "heading", "image"}
            )
            self.assertEqual(article.metadata["original_images"], ["https://mmbiz.qpic.cn/x.png"])
            self.assertEqual(article.metadata["content_origin"], "manual_url_fetch")
            # 正文由 AIRADAR 自己抓,不再绕 SourcePilot
            self.assertFalse(any("/api/v1/article" in u for u in harness.requests))
            # 绝不进 deferred 路径:mp.weixin 在 UNFETCHABLE_ARTICLE_DOMAINS,
            # deferred 会让管线自己去抓并直接放弃
            self.assertNotIn("body_fetch", article.metadata)

    def test_article_failure_degrades_to_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            harness = CrawlerHarness(make_source(), tmpdir)
            harness.items_responses = [make_envelope([make_item()])]
            harness.extract_error = RuntimeError("fetch_failed")
            articles = self._run(harness)
            article = articles[0]
            self.assertEqual(article.content, "新一代旗舰模型")
            self.assertEqual(article.metadata["content_origin"], "sourcepilot_summary")
            self.assertEqual(article.metadata["sp_body"], "missing")
            # 失败不写缓存,下轮重试
            self.assertEqual(list(harness.cache_dir.glob("*.json")), [])

    def test_article_cache_hit_skips_network_and_budget(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            harness = CrawlerHarness(make_source(sp_article_limit=0), tmpdir)
            harness.items_responses = [make_envelope([make_item()])]
            articles_first = self._run(harness)
            # 预算 0 且无缓存:降级,不做提取
            self.assertEqual(articles_first[0].metadata["sp_body"], "missing")
            self.assertEqual(harness.extract_calls, [])
            # 预写缓存后,预算 0 也能拿到正文(缓存命中不占预算)
            from app.crawlers.sourcepilot import _CACHE_VERSION

            cached = extracted_article("缓存正文")
            cache_key = articles_first[0].url_hash
            harness.cache_dir.mkdir(parents=True, exist_ok=True)
            (harness.cache_dir / f"{cache_key}.json").write_text(
                json.dumps({"v": _CACHE_VERSION, "extracted": cached}), encoding="utf-8"
            )
            harness.items_responses = [make_envelope([make_item()])]
            harness.extract_calls.clear()
            articles_second = self._run(harness)
            self.assertEqual(articles_second[0].content, "缓存正文")
            self.assertEqual(harness.extract_calls, [])

    def test_budget_limits_network_calls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            harness = CrawlerHarness(make_source(sp_article_limit=1), tmpdir)
            items = [
                make_item(url="https://mp.weixin.qq.com/s/a"),
                make_item(url="https://mp.weixin.qq.com/s/b"),
            ]
            harness.items_responses = [make_envelope(items)]
            articles = self._run(harness)
            self.assertEqual(len(harness.extract_calls), 1)
            enriched = [a for a in articles if a.metadata.get("original_blocks")]
            degraded = [a for a in articles if a.metadata.get("sp_body") == "missing"]
            self.assertEqual(len(enriched), 1)
            self.assertEqual(len(degraded), 1)

    def test_pagination_passes_cursor_and_account(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            harness = CrawlerHarness(make_source(), tmpdir)
            harness.items_responses = [
                make_envelope(
                    [make_item(url="https://mp.weixin.qq.com/s/p1")],
                    next_cursor="CURSOR-1",
                    has_more=True,
                ),
                make_envelope(
                    [
                        make_item(
                            url="https://mp.weixin.qq.com/s/p2",
                            discovered_at="2026-08-02T00:00:00Z",
                        )
                    ]
                ),
            ]
            articles = self._run(harness)
            self.assertEqual(len(articles), 2)
            feed_calls = [u for u in harness.requests if "/api/v1/wechat/feed" in u]
            self.assertEqual(len(feed_calls), 2)
            # 按号过滤走 account 参数(/items 的 platform 白名单不认公众号名)
            self.assertIn("account=%E6%99%BA%E8%B0%B1", feed_calls[0])
            # recent_days=0 → window=all
            self.assertIn("window=all", feed_calls[0])
            # cursor 原样透传,不解析
            self.assertIn("cursor=CURSOR-1", feed_calls[1])
            self.assertNotIn("cursor", feed_calls[0])

    def test_window_maps_from_recent_days(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            harness = CrawlerHarness(make_source(recent_days=7), tmpdir)
            # 用远期条目防被 recent_days 剪枝干扰,只看请求参数
            harness.items_responses = [make_envelope([])]
            self._run(harness)
            feed_call = next(u for u in harness.requests if "/api/v1/wechat/feed" in u)
            self.assertIn("window=7d", feed_call)


    def test_other_error_codes_raise(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            harness = CrawlerHarness(make_source(), tmpdir)
            harness.items_responses = [
                make_envelope(
                    ok=False,
                    error={"code": "UPSTREAM_DOWN", "message": "backend gone"},
                )
            ]
            with self.assertRaises(RuntimeError) as ctx:
                self._run(harness)
            self.assertIn("UPSTREAM_DOWN", str(ctx.exception))

    def test_contract_major_version_change_logs_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            harness = CrawlerHarness(make_source(), tmpdir)
            harness.items_responses = [make_envelope([], version="2.0.0")]
            with self.assertLogs("app.crawlers.sourcepilot", level="ERROR") as logs:
                self._run(harness)
            self.assertTrue(
                any("contract major version" in line for line in logs.output)
            )



class StatelessnessTests(unittest.TestCase):
    """fetch() 必须无副作用状态——这是踩过一次的坑，别让它回来。

    `BaseCrawler.fetch()` 没有「已成功落库」的信号：crawl_sources() 只负责抓，
    落库在后面的 pipeline。第一版在 fetch 里存了 since 水位，结果一轮抓到的
    47 篇因为后续没走到落库而全丢，水位却已经跨过它们——永久漏掉，下一轮拉回 0 条。
    这与 we-mp-rss #440 是同一个 bug。现在靠 recent_days 限窗 + 入库 url_hash 去重。
    """

    def test_fetch_writes_no_progress_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            harness = CrawlerHarness(make_source(), tmpdir)
            harness.items_responses = [make_envelope([make_item()])]
            self._run_once(harness)
            written = {p.name for p in Path(tmpdir).rglob("*") if p.is_file()}
            # 只该有正文缓存，不该有任何「上次抓到哪」的游标文件
            self.assertTrue(all(name.endswith(".json") for name in written))
            self.assertEqual(
                [p for p in Path(tmpdir).rglob("*") if p.is_dir() and p.name == "state"],
                [],
            )

    def test_repeated_fetch_returns_the_same_items(self):
        """重复抓取必须仍然返回条目——去重是入库层的事（url_hash），
        不是 crawler 的事。crawler 私自跳过就等于把数据丢在管线之外。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            harness = CrawlerHarness(make_source(), tmpdir)
            harness.items_responses = [make_envelope([make_item()])]
            first = self._run_once(harness)
            harness.items_responses = [make_envelope([make_item()])]
            second = self._run_once(harness)
            self.assertEqual(len(first), 1)
            self.assertEqual(len(second), 1)
            self.assertEqual(first[0].url_hash, second[0].url_hash)

    def _run_once(self, harness):
        with patch(
            "app.crawlers.sourcepilot.fetch_url_text", side_effect=harness.fake_fetch
        ):
            return harness.crawler.fetch()

    def test_crawler_has_no_state_dir_parameter(self):
        import inspect

        params = inspect.signature(SourcePilotCrawler.__init__).parameters
        self.assertNotIn("state_dir", params)


class RegistryTests(unittest.TestCase):
    def test_sourcepilot_type_dispatches(self):
        crawler = crawler_for_source(make_source())
        self.assertIsInstance(crawler, SourcePilotCrawler)


if __name__ == "__main__":
    unittest.main()

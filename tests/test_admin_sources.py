from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:
    TestClient = None

AUTH = {"Authorization": "Bearer secret-token"}


@unittest.skipIf(TestClient is None, "FastAPI is not installed in this environment")
class AdminSourcesApiTests(unittest.TestCase):
    def setUp(self):
        self.repository = _FakeSourceRepository()
        env = patch.dict("os.environ", {"ADMIN_TOKEN": "secret-token"})
        env.start()
        self.addCleanup(env.stop)

    def _client(self):
        from app import main as module

        app = module.create_app(report_repository_factory=lambda: self.repository)
        return TestClient(app)

    def test_list_sources_requires_auth_and_returns_health(self):
        client = self._client()

        denied = client.get("/api/admin/sources")
        response = client.get("/api/admin/sources", headers=AUTH)

        self.assertEqual(denied.status_code, 401)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sources"][0]["id"], "openai_blog")
        self.assertTrue(
            {
                "aihot_feed",
                "telegram_zaihuapd",
                "telegram_xhqcankao",
                "telegram_dnspodt",
            }.issubset({source.id for source in self.repository.created})
        )

    def test_patch_source_updates_allowed_fields_only(self):
        client = self._client()

        response = client.patch(
            "/api/admin/sources/openai_blog",
            headers=AUTH,
            json={"is_active": False, "tier": "T2", "id": "hack", "success_rate": 9},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.repository.updates, [("openai_blog", {"is_active": False, "tier": "T2"})]
        )

    def test_patch_unknown_source_returns_404(self):
        client = self._client()

        response = client.patch(
            "/api/admin/sources/nope", headers=AUTH, json={"is_active": False}
        )

        self.assertEqual(response.status_code, 404)

    def test_create_source_validates_required_fields(self):
        client = self._client()

        missing = client.post("/api/admin/sources", headers=AUTH, json={"name": "X"})
        created = client.post(
            "/api/admin/sources",
            headers=AUTH,
            json={
                "id": "new_blog",
                "name": "New Blog",
                "type": "rss",
                "url": "https://new.example/feed.xml",
                "homepage": "https://new.example",
                "tier": "T2",
                "category": "media",
            },
        )

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(created.status_code, 200)
        self.assertEqual(self.repository.created[0].id, "new_blog")
        self.assertEqual(self.repository.created[0].source_role, "context")

    def test_test_endpoint_scores_and_saves_new_articles(self):
        # 手动抓取现在要真正跑内容检查/AI 评分/入库，不再只是连通性预览
        from datetime import datetime, timezone

        from app.models.domain import RawArticle
        from app.services.ai_service import FakeAIProvider

        client = self._client()

        class FakeCrawler:
            def fetch(self, limit=None):
                return [
                    RawArticle(
                        id="manual-1",
                        source_id="openai_blog",
                        source_name="OpenAI Blog",
                        source_role="authority",
                        source_tier="T1",
                        source_url="https://x.example/a",
                        title="OpenAI announces new model release",
                        content="OpenAI announces a new model release with agent capabilities.",
                        author="OpenAI",
                        published_at=datetime.now(timezone.utc),
                        language="en",
                        raw_score={},
                        metadata={},
                        title_hash="th-1",
                        url_hash="uh-manual-1",
                    )
                ]

        with patch("app.crawlers.registry.crawler_for_source", return_value=FakeCrawler()), patch(
            "app.services.ai_service.provider_from_env", return_value=FakeAIProvider()
        ):
            response = client.post("/api/admin/sources/openai_blog/test", headers=AUTH)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["origin"], "manual")
        article = body["articles"][0]
        self.assertEqual(article["title"], "OpenAI announces new model release")
        self.assertEqual(article["outcome"], "saved")
        self.assertTrue(article["selected"])
        self.assertIsInstance(article["final_score"], (int, float))
        # actually persisted, not just previewed
        self.assertEqual(len(self.repository.raw_upserts), 1)
        self.assertEqual(len(self.repository.processed_upserts), 1)
        self.assertTrue(
            self.repository.raw_upserts[0].metadata.get("translated_paragraphs")
        )
        self.assertEqual(self.repository.crawl_results[-1][0], "openai_blog")
        self.assertEqual(self.repository.health_updates[-1]["openai_blog"]["status"], "ok")

    def test_test_endpoint_reports_duplicate_without_rescoring(self):
        from datetime import datetime, timezone

        from app.models.domain import RawArticle
        from app.services.ai_service import FakeAIProvider

        client = self._client()
        self.repository.existing_outcomes["uh-dup"] = {
            "title": "Previously seen article",
            "url": "https://x.example/dup",
            "selected": True,
            "final_score": 88.0,
            "category": "model_release",
            "reason": "final_score:88.0>=threshold:65",
        }
        self.repository.cached_results["uh-dup"] = {
            "raw_article_id": "manual-2",
            "language": "en",
            "content": "content",
            "metadata": {"translated_paragraphs": ["缓存译文"]},
        }

        class FakeCrawler:
            def fetch(self, limit=None):
                return [
                    RawArticle(
                        id="manual-2",
                        source_id="openai_blog",
                        source_name="OpenAI Blog",
                        source_role="authority",
                        source_tier="T1",
                        source_url="https://x.example/dup",
                        title="Previously seen article",
                        content="content",
                        author="OpenAI",
                        published_at=datetime.now(timezone.utc),
                        language="en",
                        raw_score={},
                        metadata={},
                        title_hash="th-2",
                        url_hash="uh-dup",
                    )
                ]

        with patch("app.crawlers.registry.crawler_for_source", return_value=FakeCrawler()), patch(
            "app.services.ai_service.provider_from_env", return_value=FakeAIProvider()
        ):
            response = client.post("/api/admin/sources/openai_blog/test", headers=AUTH)

        body = response.json()
        self.assertEqual(body["articles"][0]["outcome"], "duplicate")
        self.assertEqual(body["articles"][0]["final_score"], 88.0)
        # no re-processing spent on an article we already have a verdict for
        self.assertEqual(len(self.repository.processed_upserts), 0)

    def test_test_endpoint_repairs_missing_translation_for_duplicate(self):
        from datetime import datetime, timezone

        from app.models.domain import RawArticle
        from app.services.ai_service import FakeAIProvider

        client = self._client()
        self.repository.existing_outcomes["uh-repair"] = {
            "title": "Previously seen article",
            "url": "https://x.example/repair",
            "selected": True,
            "final_score": 88.0,
            "category": "model_release",
            "reason": "final_score:88.0>=threshold:65",
        }
        self.repository.cached_results["uh-repair"] = {
            "raw_article_id": "manual-repair",
            "language": "en",
            "content": "Full English article body about an OpenAI agent model.",
            "metadata": {
                "content_extraction_version": 2,
                "original_paragraphs": [
                    "Full English article body about an OpenAI agent model."
                ],
                "original_blocks": [
                    {
                        "type": "paragraph",
                        "text": "Full English article body about an OpenAI agent model.",
                    }
                ],
            },
            "scoring": {
                "dimensions": {
                    "ai_relevance": 9,
                    "novelty": 8,
                    "impact": 8,
                    "information_density": 8,
                    "actionability": 7,
                    "creator_value": 7,
                },
                "category": "model_release",
                "tags": ["OpenAI"],
                "title_zh": "既有中文标题",
                "one_line_summary": "摘要",
                "summary_zh": "摘要",
                "reason_zh": "理由",
                "action_zh": "行动",
            },
        }

        class FakeCrawler:
            def fetch(self, limit=None):
                return [
                    RawArticle(
                        id="fresh-id",
                        source_id="openai_blog",
                        source_name="OpenAI Blog",
                        source_role="authority",
                        source_tier="T1",
                        source_url="https://x.example/repair",
                        title="Previously seen article",
                        content="RSS teaser",
                        author="OpenAI",
                        published_at=datetime.now(timezone.utc),
                        language="en",
                        raw_score={},
                        metadata={"body_fetch": "deferred"},
                        title_hash="th-repair",
                        url_hash="uh-repair",
                    )
                ]

        class NoRescoreProvider(FakeAIProvider):
            def score_article(self, title, content):
                raise AssertionError("cached duplicate must not be rescored")

        with patch("app.crawlers.registry.crawler_for_source", return_value=FakeCrawler()), patch(
            "app.services.ai_service.provider_from_env", return_value=NoRescoreProvider()
        ):
            response = client.post("/api/admin/sources/openai_blog/test", headers=AUTH)

        body = response.json()
        self.assertEqual(body["articles"][0]["outcome"], "duplicate")
        self.assertEqual(body["ingested_count"], 0)
        self.assertEqual(body["accepted_count"], 0)
        repaired = self.repository.raw_upserts[0]
        self.assertEqual(repaired.id, "manual-repair")
        self.assertEqual(repaired.content, "Full English article body about an OpenAI agent model.")
        self.assertTrue(repaired.metadata.get("translated_paragraphs"))

    def test_test_endpoint_translation_failure_does_not_fail_source_sync(self):
        from datetime import datetime, timezone

        from app.models.domain import RawArticle
        from app.services.ai_service import FakeAIProvider

        class FakeCrawler:
            def fetch(self, limit=None):
                return [
                    RawArticle(
                        id="translation-fails",
                        source_id="openai_blog",
                        source_name="OpenAI Blog",
                        source_role="authority",
                        source_tier="T1",
                        source_url="https://x.example/translation-fails",
                        title="OpenAI agent model update",
                        content="A sufficiently detailed English article about an AI agent model.",
                        author="OpenAI",
                        published_at=datetime.now(timezone.utc),
                        language="en",
                        raw_score={},
                        metadata={},
                        title_hash="th-translation-fails",
                        url_hash="uh-translation-fails",
                    )
                ]

        class TranslationFailsProvider(FakeAIProvider):
            def translate_paragraphs(self, paragraphs):
                raise RuntimeError("translation unavailable")

        with patch("app.crawlers.registry.crawler_for_source", return_value=FakeCrawler()), patch(
            "app.services.ai_service.provider_from_env",
            return_value=TranslationFailsProvider(),
        ):
            response = self._client().post(
                "/api/admin/sources/openai_blog/test", headers=AUTH
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(
            self.repository.raw_upserts[0].metadata.get("translation_status"), "failed"
        )

    def test_test_endpoint_does_not_translate_chinese_article(self):
        from datetime import datetime, timezone

        from app.models.domain import RawArticle
        from app.services.ai_service import FakeAIProvider

        class FakeCrawler:
            def fetch(self, limit=None):
                return [
                    RawArticle(
                        id="manual-zh",
                        source_id="openai_blog",
                        source_name="OpenAI Blog",
                        source_role="authority",
                        source_tier="T1",
                        source_url="https://x.example/zh",
                        title="人工智能代理模型发布",
                        content="这是一篇介绍人工智能代理模型发布及其工具调用能力的中文正文。",
                        author="OpenAI",
                        published_at=datetime.now(timezone.utc),
                        language="zh",
                        raw_score={},
                        metadata={},
                        title_hash="th-zh",
                        url_hash="uh-zh",
                    )
                ]

        class TranslationMustNotRunProvider(FakeAIProvider):
            def translate_paragraphs(self, paragraphs):
                raise AssertionError("Chinese content must not enter translation")

        with patch("app.crawlers.registry.crawler_for_source", return_value=FakeCrawler()), patch(
            "app.services.ai_service.provider_from_env",
            return_value=TranslationMustNotRunProvider(),
        ):
            response = self._client().post(
                "/api/admin/sources/openai_blog/test", headers=AUTH
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertNotIn("translation_status", self.repository.raw_upserts[0].metadata)
        self.assertNotIn("translated_paragraphs", self.repository.raw_upserts[0].metadata)

    def test_test_endpoint_reports_fetch_errors(self):
        client = self._client()

        class BoomCrawler:
            def fetch(self, limit=None):
                raise RuntimeError("HTTP Error 404")

        with patch("app.crawlers.registry.crawler_for_source", return_value=BoomCrawler()):
            response = client.post("/api/admin/sources/openai_blog/test", headers=AUTH)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "failed")
        self.assertIn("404", body["error"])
        self.assertEqual(
            self.repository.health_updates[-1]["openai_blog"]["status"], "skipped"
        )


@unittest.skipIf(TestClient is None, "FastAPI is not installed in this environment")
class AdminEventsApiTests(unittest.TestCase):
    def setUp(self):
        self.repository = _FakeSourceRepository()
        env = patch.dict("os.environ", {"ADMIN_TOKEN": "secret-token"})
        env.start()
        self.addCleanup(env.stop)

    def _client(self):
        from app import main as module

        app = module.create_app(report_repository_factory=lambda: self.repository)
        return TestClient(app)

    def test_admin_events_lists_hidden_items(self):
        client = self._client()

        response = client.get("/api/admin/events?days=7", headers=AUTH)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["items"][0]["event_id"], "aa1")
        self.assertTrue(self.repository.admin_listed_with_hidden)

    def test_admin_events_supports_search_and_pagination(self):
        client = self._client()
        self.repository.event_items = [
            {"event_id": f"a{i}", "title": f"OpenAI story {i}", "hidden": False, "published_at": f"2026-07-{10-i:02d}T00:00:00+00:00"}
            for i in range(5)
        ] + [{"event_id": "b1", "title": "Claude update", "hidden": False, "published_at": "2026-07-01T00:00:00+00:00"}]

        searched = client.get("/api/admin/events?q=claude", headers=AUTH)
        paged = client.get("/api/admin/events?limit=2&offset=2", headers=AUTH)

        self.assertEqual(searched.status_code, 200)
        body = searched.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["event_id"], "b1")
        pbody = paged.json()
        self.assertEqual(pbody["total"], 6)
        self.assertEqual(len(pbody["items"]), 2)

    def test_patch_event_moderation_validates_category(self):
        client = self._client()

        bad = client.patch(
            "/api/admin/events/aa1", headers=AUTH, json={"category": "nonsense"}
        )
        good = client.patch(
            "/api/admin/events/aa1",
            headers=AUTH,
            json={"hidden": True, "category": "research", "extra": "x"},
        )
        missing = client.patch(
            "/api/admin/events/a-none", headers=AUTH, json={"hidden": True}
        )

        self.assertEqual(bad.status_code, 400)
        self.assertEqual(good.status_code, 200)
        self.assertEqual(
            self.repository.moderations,
            [("aa1", {"hidden": True, "category": "research"})],
        )
        self.assertEqual(missing.status_code, 404)


class _FakeSession:
    def commit(self):
        pass


class _FakeSourceRepository:
    def __init__(self):
        self.updates = []
        self.created = []
        self.session = _FakeSession()
        self.raw_upserts = []
        self.processed_upserts = []
        self.embedding_upserts = []
        self.crawl_results = []
        self.health_updates = []
        self.existing_outcomes = {}
        self.cached_results = {}

    def get_cached_results_by_url_hash(self, url_hashes):
        return {
            url_hash: self.cached_results[url_hash]
            for url_hash in url_hashes
            if url_hash in self.cached_results
        }

    def get_existing_outcome_by_url_hash(self, url_hash):
        return self.existing_outcomes.get(url_hash)

    def upsert_raw_articles(self, articles, **kwargs):
        self.raw_upserts.extend(articles)

    def upsert_processed_articles(self, processed_articles, **kwargs):
        self.processed_upserts.extend(processed_articles)

    def upsert_article_embedding(self, raw_article_id, **kwargs):
        self.embedding_upserts.append((raw_article_id, kwargs))

    def set_last_crawl_result(self, source_id, result):
        self.crawl_results.append((source_id, result))

    def update_source_health(self, per_source):
        self.health_updates.append(per_source)

    def list_sources_with_health(self):
        return [{"id": "openai_blog", "name": "OpenAI Blog", "success_rate": 1.0}]

    def get_all_sources(self):
        from app.models.domain import Source

        return [
            Source(
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
        ]

    def update_source_fields(self, source_id, fields):
        if source_id != "openai_blog":
            return False
        self.updates.append((source_id, fields))
        return True

    def upsert_sources(self, sources):
        self.created.extend(sources)

    admin_listed_with_hidden = False
    moderations: list = []

    event_items = None

    def get_all_event_items_between(self, start_date, end_date, include_hidden=False):
        self.admin_listed_with_hidden = include_hidden
        if self.event_items is not None:
            return list(self.event_items)
        return [{"event_id": "aa1", "title": "t", "hidden": False}]

    def update_event_moderation(self, event_id, fields):
        if event_id == "a-none":
            return False
        self.moderations.append((event_id, fields))
        return True


if __name__ == "__main__":
    unittest.main()

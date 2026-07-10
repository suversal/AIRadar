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

    def test_test_endpoint_returns_sample_titles(self):
        client = self._client()

        class FakeCrawler:
            def fetch(self, limit=None):
                class A:
                    title = "Sample article"
                    source_url = "https://x.example/a"

                return [A()]

        with patch("app.crawlers.registry.crawler_for_source", return_value=FakeCrawler()):
            response = client.post("/api/admin/sources/openai_blog/test", headers=AUTH)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["articles"][0]["title"], "Sample article")

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


class _FakeSourceRepository:
    def __init__(self):
        self.updates = []
        self.created = []

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

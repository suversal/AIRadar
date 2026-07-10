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


if __name__ == "__main__":
    unittest.main()

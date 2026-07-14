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


class _FakeSession:
    def commit(self):
        pass


class _FakeEventRepository:
    def __init__(self):
        self.session = _FakeSession()
        self.deleted_event_ids: list[str] = []
        self.deletable_event_ids = {"e-real", "apseudo12345"}

    def delete_raw_article(self, event_id: str) -> bool:
        self.deleted_event_ids.append(event_id)
        return event_id in self.deletable_event_ids


@unittest.skipIf(TestClient is None, "FastAPI is not installed in this environment")
class AdminEventsDeleteApiTests(unittest.TestCase):
    def setUp(self):
        self.repository = _FakeEventRepository()
        env = patch.dict("os.environ", {"ADMIN_TOKEN": "secret-token"})
        env.start()
        self.addCleanup(env.stop)

    def _client(self):
        from app import main as module

        app = module.create_app(report_repository_factory=lambda: self.repository)
        return TestClient(app)

    def test_delete_event_requires_auth(self):
        client = self._client()

        denied = client.delete("/api/admin/events/e-real")

        self.assertEqual(denied.status_code, 401)
        self.assertEqual(self.repository.deleted_event_ids, [])

    def test_delete_known_event_returns_ok_with_raw_article_id(self):
        client = self._client()

        response = client.delete("/api/admin/events/e-real", headers=AUTH)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "deleted_raw_article_id": "e-real"})
        self.assertEqual(self.repository.deleted_event_ids, ["e-real"])

    def test_delete_unknown_event_returns_404(self):
        client = self._client()

        response = client.delete("/api/admin/events/nope", headers=AUTH)

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()

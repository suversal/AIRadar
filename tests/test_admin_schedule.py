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
class AdminScheduleApiTests(unittest.TestCase):
    def setUp(self):
        self.repository = _FakeScheduleRepository()
        env = patch.dict("os.environ", {"ADMIN_TOKEN": "secret-token"})
        env.start()
        self.addCleanup(env.stop)

    def _client(self):
        from app import main as module

        app = module.create_app(report_repository_factory=lambda: self.repository)
        return TestClient(app)

    def test_get_schedule_requires_auth_and_returns_config(self):
        client = self._client()

        denied = client.get("/api/admin/schedule")
        response = client.get("/api/admin/schedule", headers=AUTH)

        self.assertEqual(denied.status_code, 401)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["enabled"], False)
        self.assertEqual(response.json()["interval_minutes"], 120)

    def test_put_schedule_updates_enabled_and_interval(self):
        client = self._client()

        response = client.put(
            "/api/admin/schedule",
            headers=AUTH,
            json={"enabled": True, "interval_minutes": 30},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.repository.updates, [(True, 30)])
        self.assertTrue(self.repository.committed)

    def test_put_schedule_rejects_interval_out_of_range(self):
        client = self._client()

        response = client.put(
            "/api/admin/schedule",
            headers=AUTH,
            json={"enabled": True, "interval_minutes": 1},
        )

        self.assertEqual(response.status_code, 400)


class _FakeScheduleRepository:
    def __init__(self):
        self.updates = []
        self.committed = False
        self.config = {
            "enabled": False,
            "interval_minutes": 120,
            "last_triggered_at": None,
            "updated_at": None,
        }

    def get_schedule_config(self):
        return dict(self.config)

    def update_schedule_config(self, *, enabled, interval_minutes):
        self.updates.append((enabled, interval_minutes))
        self.config.update({"enabled": enabled, "interval_minutes": interval_minutes})
        return dict(self.config)

    @property
    def session(self):
        return self

    def commit(self):
        self.committed = True


if __name__ == "__main__":
    unittest.main()

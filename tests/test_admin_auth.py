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


@unittest.skipIf(TestClient is None, "FastAPI is not installed in this environment")
class AdminAuthTests(unittest.TestCase):
    def _client(self):
        from app import main as module

        app = module.create_app(report_repository_factory=lambda: _FakeRepository())
        return TestClient(app)

    def test_admin_routes_reject_missing_token(self):
        with patch.dict("os.environ", {"ADMIN_TOKEN": "secret-token"}):
            client = self._client()

            ping = client.get("/api/admin/ping")
            refresh = client.post("/api/admin/refresh-latest")

        self.assertEqual(ping.status_code, 401)
        self.assertEqual(refresh.status_code, 401)

    def test_admin_routes_reject_wrong_token(self):
        with patch.dict("os.environ", {"ADMIN_TOKEN": "secret-token"}):
            client = self._client()

            response = client.get(
                "/api/admin/ping", headers={"Authorization": "Bearer wrong"}
            )

        self.assertEqual(response.status_code, 401)

    def test_admin_routes_accept_bearer_token(self):
        with patch.dict("os.environ", {"ADMIN_TOKEN": "secret-token"}):
            client = self._client()

            response = client.get(
                "/api/admin/ping", headers={"Authorization": "Bearer secret-token"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_admin_routes_accept_cookie_token(self):
        with patch.dict("os.environ", {"ADMIN_TOKEN": "secret-token"}):
            client = self._client()
            client.cookies.set("admin_token", "secret-token")

            response = client.get("/api/admin/ping")

        self.assertEqual(response.status_code, 200)

    def test_admin_routes_disabled_without_configured_token(self):
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("ADMIN_TOKEN", None)
            client = self._client()

            response = client.get(
                "/api/admin/ping", headers={"Authorization": "Bearer anything"}
            )

        self.assertEqual(response.status_code, 403)
        self.assertIn("ADMIN_TOKEN", response.json()["detail"])

    def test_public_routes_stay_open(self):
        with patch.dict("os.environ", {"ADMIN_TOKEN": "secret-token"}):
            client = self._client()

            response = client.get("/api/public/latest")

        self.assertEqual(response.status_code, 200)


class _FakeRepository:
    def get_latest_daily_report_payload(self):
        return None

    def get_daily_report_payload(self, report_date):
        return None

    def get_daily_report_payloads_between(self, start_date, end_date):
        return []

    def get_all_event_items_between(self, start_date, end_date):
        return []

    def get_event_item(self, event_id):
        return None


if __name__ == "__main__":
    unittest.main()

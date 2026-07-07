import importlib
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - local lightweight env may omit FastAPI
    TestClient = None


class APIMainTests(unittest.TestCase):
    def test_main_module_imports_without_fastapi_installed(self):
        module = importlib.import_module("app.main")

        self.assertTrue(hasattr(module, "create_app"))
        self.assertTrue(hasattr(module, "app"))

    @unittest.skipIf(TestClient is None, "FastAPI is not installed in this environment")
    def test_public_routes_can_read_from_repository(self):
        module = importlib.import_module("app.main")
        repository = FakeRepository(
            {
                date(2026, 7, 2): {
                    "report_date": "2026-07-02",
                    "title": "Suversal AI Radar 日报 - 2026-07-02",
                    "summary": "精选 12 条 AI 情报。",
                    "updated_at": "2026-07-02T09:00:00+00:00",
                    "sections": {"model_release": []},
                    "items": [{"event_id": "c1"}],
                    "article_count": 12,
                }
            }
        )
        client = TestClient(module.create_app(report_repository_factory=lambda: repository))

        latest = client.get("/api/public/latest").json()
        daily = client.get("/api/public/daily/2026-07-02").json()

        self.assertEqual(latest["items"][0]["event_id"], "c1")
        self.assertEqual(daily["report_date"], "2026-07-02")
        self.assertEqual(repository.calls, ["latest", "daily:2026-07-02"])

    @unittest.skipIf(TestClient is None, "FastAPI is not installed in this environment")
    def test_public_daily_route_returns_empty_payload_for_missing_repository_date(self):
        module = importlib.import_module("app.main")
        client = TestClient(module.create_app(report_repository_factory=lambda: FakeRepository({})))

        daily = client.get("/api/public/daily/2026-07-03").json()

        self.assertEqual(daily["report_date"], "2026-07-03")
        self.assertEqual(daily["items"], [])
        self.assertEqual(daily["article_count"], 0)

    @unittest.skipIf(TestClient is None, "FastAPI is not installed in this environment")
    def test_refresh_latest_route_calls_refresh_runner(self):
        module = importlib.import_module("app.main")
        calls = []

        def refresh_runner(*, limit, top_n):
            calls.append({"limit": limit, "top_n": top_n})
            return {"status": "ok", "report_date": "2026-07-07", "article_count": top_n}

        client = TestClient(module.create_app(refresh_runner=refresh_runner))

        response = client.post("/api/admin/refresh-latest?limit=80&top_n=30")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["report_date"], "2026-07-07")
        self.assertEqual(response.json()["article_count"], 30)
        self.assertEqual(calls, [{"limit": 80, "top_n": 30}])


class FakeRepository:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def get_latest_daily_report_payload(self):
        self.calls.append("latest")
        if not self.payloads:
            return None
        latest_date = sorted(self.payloads)[-1]
        return self.payloads[latest_date]

    def get_daily_report_payload(self, report_date):
        self.calls.append(f"daily:{report_date.isoformat()}")
        return self.payloads.get(report_date)


if __name__ == "__main__":
    unittest.main()

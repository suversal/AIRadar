import importlib
import sys
import time
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

        import os
        from unittest.mock import patch as env_patch

        env = env_patch.dict(os.environ, {"ADMIN_TOKEN": "test-admin"})
        env.start()
        self.addCleanup(env.stop)
        client = TestClient(module.create_app(refresh_runner=refresh_runner))
        client.headers.update({"Authorization": "Bearer test-admin"})

        response = client.post("/api/admin/refresh-latest?limit=80&top_n=30")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["report_date"], "2026-07-07")
        self.assertEqual(response.json()["article_count"], 30)
        self.assertEqual(calls, [{"limit": 80, "top_n": 30}])

    @unittest.skipIf(TestClient is None, "FastAPI is not installed in this environment")
    def test_refresh_latest_async_route_tracks_job_result(self):
        module = importlib.import_module("app.main")

        def refresh_runner(*, limit, top_n):
            return {
                "status": "ok",
                "report_date": "2026-07-07",
                "limit": limit,
                "top_n": top_n,
                "article_count": top_n,
            }

        import os
        from unittest.mock import patch as env_patch

        env = env_patch.dict(os.environ, {"ADMIN_TOKEN": "test-admin"})
        env.start()
        self.addCleanup(env.stop)
        client = TestClient(module.create_app(refresh_runner=refresh_runner))
        client.headers.update({"Authorization": "Bearer test-admin"})

        response = client.post("/api/admin/refresh-latest-async?limit=20&top_n=9")

        self.assertEqual(response.status_code, 200)
        job_id = response.json()["job_id"]
        job_payload = None
        for _ in range(20):
            job_response = client.get(f"/api/admin/refresh-jobs/{job_id}")
            job_payload = job_response.json()
            if job_payload["status"] != "running":
                break
            time.sleep(0.01)

        self.assertEqual(job_payload["status"], "succeeded")
        self.assertEqual(job_payload["result"]["article_count"], 9)
        self.assertEqual(job_payload["result"]["limit"], 20)


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


class FakeScheduleRepository:
    def __init__(self, config):
        self.config = config
        self.triggered_at = None
        self.committed = False

    def get_schedule_config(self):
        return self.config

    def record_schedule_triggered(self, triggered_at):
        self.triggered_at = triggered_at
        self.config = dict(self.config, last_triggered_at=triggered_at.isoformat())

    @property
    def session(self):
        return self

    def commit(self):
        self.committed = True


class SchedulerTickTests(unittest.TestCase):
    def test_tick_skips_when_not_due(self):
        module = importlib.import_module("app.main")
        from datetime import datetime, timezone

        repository = FakeScheduleRepository({"enabled": False, "interval_minutes": 120, "last_triggered_at": None})
        triggered = []

        result = module.run_scheduler_tick(
            repository,
            now=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc),
            is_refresh_running=lambda: False,
            trigger_refresh=lambda: triggered.append(True),
        )

        self.assertFalse(result)
        self.assertEqual(triggered, [])
        self.assertIsNone(repository.triggered_at)

    def test_tick_skips_when_refresh_already_running(self):
        module = importlib.import_module("app.main")
        from datetime import datetime, timezone

        repository = FakeScheduleRepository({"enabled": True, "interval_minutes": 120, "last_triggered_at": None})
        triggered = []

        result = module.run_scheduler_tick(
            repository,
            now=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc),
            is_refresh_running=lambda: True,
            trigger_refresh=lambda: triggered.append(True),
        )

        self.assertFalse(result)
        self.assertEqual(triggered, [])

    def test_tick_triggers_and_records_when_due(self):
        module = importlib.import_module("app.main")
        from datetime import datetime, timezone

        repository = FakeScheduleRepository({"enabled": True, "interval_minutes": 120, "last_triggered_at": None})
        triggered = []
        now = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)

        result = module.run_scheduler_tick(
            repository,
            now=now,
            is_refresh_running=lambda: False,
            trigger_refresh=lambda: triggered.append(True),
        )

        self.assertTrue(result)
        self.assertEqual(triggered, [True])
        self.assertEqual(repository.triggered_at, now)
        self.assertTrue(repository.committed)


if __name__ == "__main__":
    unittest.main()

import importlib
import sys
import time
import unittest
from datetime import date, datetime, timedelta, timezone
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
            },
            admin_items=[
                {
                    "event_id": "c1",
                    "published_at": "2026-07-11T09:00:00+00:00",
                    "final_score": 90,
                    "source_count": 1,
                }
            ],
        )
        client = TestClient(module.create_app(report_repository_factory=lambda: repository))

        latest = client.get("/api/public/latest").json()
        daily = client.get("/api/public/daily/2026-07-02").json()

        self.assertEqual(latest["items"][0]["event_id"], "c1")
        self.assertEqual(daily["report_date"], "2026-07-02")
        self.assertTrue(repository.calls[0].startswith("events:"))
        self.assertEqual(repository.calls[1], "daily:2026-07-02")

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

        def refresh_runner():
            calls.append("refresh")
            return {"status": "ok", "report_date": "2026-07-07", "article_count": 17}

        import os
        from unittest.mock import patch as env_patch

        env = env_patch.dict(os.environ, {"ADMIN_TOKEN": "test-admin"})
        env.start()
        self.addCleanup(env.stop)
        client = TestClient(module.create_app(refresh_runner=refresh_runner))
        client.headers.update({"Authorization": "Bearer test-admin"})

        response = client.post("/api/admin/refresh-latest")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["report_date"], "2026-07-07")
        self.assertEqual(response.json()["article_count"], 17)
        self.assertEqual(calls, ["refresh"])

    @unittest.skipIf(TestClient is None, "FastAPI is not installed in this environment")
    def test_refresh_latest_async_route_tracks_job_result(self):
        module = importlib.import_module("app.main")

        def refresh_runner():
            return {
                "status": "ok",
                "report_date": "2026-07-07",
                "article_count": 17,
            }

        import os
        from unittest.mock import patch as env_patch

        env = env_patch.dict(os.environ, {"ADMIN_TOKEN": "test-admin"})
        env.start()
        self.addCleanup(env.stop)
        client = TestClient(module.create_app(refresh_runner=refresh_runner))
        client.headers.update({"Authorization": "Bearer test-admin"})

        response = client.post("/api/admin/refresh-latest-async")

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
        self.assertEqual(job_payload["result"]["article_count"], 17)

    @unittest.skipIf(TestClient is None, "FastAPI is not installed in this environment")
    def test_public_hotspots_ranks_multi_source_first_and_respects_filters(self):
        module = importlib.import_module("app.main")
        now = datetime.now(timezone.utc)

        def iso(hours_ago):
            return (now - timedelta(hours=hours_ago)).isoformat()

        repository = FakeRepository(
            {},
            admin_items=[
                {
                    "event_id": "single-top",
                    "title": "Lone story",
                    "category": "model_release",
                    "final_score": 99,
                    "source_count": 1,
                    "published_at": iso(1),
                },
                {
                    "event_id": "quad",
                    "title": "Big model launch",
                    "category": "model_release",
                    "final_score": 70,
                    "source_count": 4,
                    "published_at": iso(3),
                },
                {
                    "event_id": "pair",
                    "title": "Product update",
                    "category": "product_release",
                    "final_score": 95,
                    "source_count": 2,
                    "published_at": iso(5),
                },
                {
                    "event_id": "stale",
                    "title": "Old giant",
                    "category": "model_release",
                    "final_score": 99,
                    "source_count": 6,
                    "published_at": iso(72),
                },
            ],
        )
        client = TestClient(module.create_app(report_repository_factory=lambda: repository))

        payload = client.get("/api/public/hotspots").json()
        self.assertEqual(
            [item["event_id"] for item in payload["items"]],
            ["quad", "pair", "single-top"],
        )

        filtered = client.get("/api/public/hotspots?category=model").json()
        self.assertEqual(
            [item["event_id"] for item in filtered["items"]],
            ["quad", "single-top"],
        )

        searched = client.get("/api/public/hotspots?q=product").json()
        self.assertEqual(
            [item["event_id"] for item in searched["items"]], ["pair"]
        )

    @unittest.skipIf(TestClient is None, "FastAPI is not installed in this environment")
    def test_admin_events_filters_by_title_and_category(self):
        module = importlib.import_module("app.main")
        repository = FakeRepository(
            {},
            admin_items=[
                {"event_id": "evt-1", "title": "Open model benchmark", "category": "research"},
                {"event_id": "evt-2", "title": "Open model ships", "category": "model_release"},
                {"event_id": "evt-3", "title": "Vision benchmark", "category": "research"},
            ],
        )

        import os
        from unittest.mock import patch as env_patch

        env = env_patch.dict(os.environ, {"ADMIN_TOKEN": "test-admin"})
        env.start()
        self.addCleanup(env.stop)
        client = TestClient(module.create_app(report_repository_factory=lambda: repository))
        client.headers.update({"Authorization": "Bearer test-admin"})

        response = client.get("/api/admin/events?title=open&category=research")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["event_id"], "evt-1")

        legacy_response = client.get("/api/admin/events?q=vision")
        self.assertEqual(legacy_response.json()["items"][0]["event_id"], "evt-3")

    @unittest.skipIf(TestClient is None, "FastAPI is not installed in this environment")
    def test_admin_events_filters_by_editorial_status(self):
        module = importlib.import_module("app.main")
        repository = FakeRepository(
            {},
            admin_items=[
                {"event_id": "visible", "title": "Visible", "hidden": False, "selected": False},
                {"event_id": "hidden", "title": "Hidden", "hidden": True, "selected": True},
                {"event_id": "selected", "title": "Selected", "hidden": False, "selected": True},
            ],
        )

        import os
        from unittest.mock import patch as env_patch

        env = env_patch.dict(os.environ, {"ADMIN_TOKEN": "test-admin"})
        env.start()
        self.addCleanup(env.stop)
        client = TestClient(module.create_app(report_repository_factory=lambda: repository))
        client.headers.update({"Authorization": "Bearer test-admin"})

        hidden = client.get("/api/admin/events?status=hidden").json()
        selected = client.get("/api/admin/events?status=selected").json()
        visible = client.get("/api/admin/events?status=visible").json()

        self.assertEqual([item["event_id"] for item in hidden["items"]], ["hidden"])
        self.assertEqual(
            {item["event_id"] for item in selected["items"]}, {"hidden", "selected"}
        )
        self.assertEqual(
            {item["event_id"] for item in visible["items"]}, {"visible", "selected"}
        )

    @unittest.skipIf(TestClient is None, "FastAPI is not installed in this environment")
    def test_admin_events_filters_by_main_source_and_sorts_by_published_time(self):
        module = importlib.import_module("app.main")
        repository = FakeRepository(
            {},
            admin_items=[
                {
                    "event_id": "older",
                    "title": "Older crawl",
                    "main_source": {"id": "openai_blog", "name": "OpenAI"},
                    "crawled_at": "2026-07-11T08:00:00+00:00",
                    "published_at": "2026-07-11T10:00:00+00:00",
                },
                {
                    "event_id": "other-source",
                    "title": "Other source",
                    "main_source": {"id": "anthropic_news", "name": "Anthropic"},
                    "crawled_at": "2026-07-11T12:00:00+00:00",
                    "published_at": "2026-07-11T12:00:00+00:00",
                },
                {
                    "event_id": "newer",
                    "title": "Newer crawl",
                    "main_source": {"id": "openai_blog", "name": "OpenAI"},
                    "crawled_at": "2026-07-11T11:00:00+00:00",
                    "published_at": "2026-07-11T09:00:00+00:00",
                },
                {
                    "event_id": "undated",
                    "title": "Missing timestamps",
                    "main_source": {"id": "openai_blog", "name": "OpenAI"},
                    "crawled_at": None,
                    "published_at": None,
                },
            ],
        )

        import os
        from unittest.mock import patch as env_patch

        env = env_patch.dict(os.environ, {"ADMIN_TOKEN": "test-admin"})
        env.start()
        self.addCleanup(env.stop)
        client = TestClient(module.create_app(report_repository_factory=lambda: repository))
        client.headers.update({"Authorization": "Bearer test-admin"})

        response = client.get("/api/admin/events?source_id=openai_blog")

        self.assertEqual(response.status_code, 200)
        # 内容管理按发布时间倒序(2026-07-12):older 发布于 10:00,晚于
        # newer 的 09:00,所以排在前——抓取时间只作并列时的次序
        self.assertEqual(
            [item["event_id"] for item in response.json()["items"]],
            ["older", "newer", "undated"],
        )

        crawled_desc = client.get(
            "/api/admin/events?source_id=openai_blog&sort_by=crawled_at&sort_dir=desc"
        )
        self.assertEqual(
            [item["event_id"] for item in crawled_desc.json()["items"]],
            ["newer", "older", "undated"],
        )
        self.assertEqual(crawled_desc.json()["sort_by"], "crawled_at")
        self.assertEqual(crawled_desc.json()["sort_dir"], "desc")

        crawled_asc = client.get(
            "/api/admin/events?source_id=openai_blog&sort_by=crawled_at&sort_dir=asc"
        )
        self.assertEqual(
            [item["event_id"] for item in crawled_asc.json()["items"]],
            ["older", "newer", "undated"],
        )

        invalid = client.get("/api/admin/events?sort_by=score&sort_dir=sideways")
        self.assertEqual(invalid.status_code, 400)


class FakeRepository:
    def __init__(self, payloads, admin_items=None):
        self.payloads = payloads
        self.admin_items = admin_items or []
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

    def get_all_event_items_between(
        self, start_date, end_date, *, include_hidden=False, selected_only=False
    ):
        self.calls.append(f"events:{start_date.isoformat()}:{end_date.isoformat()}")
        return list(self.admin_items)


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

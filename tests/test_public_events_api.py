from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.api.public import (
    build_events_payload,
    build_period_payload,
    month_range,
    week_range,
)

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:
    TestClient = None


def make_daily_payload(report_date: str, items: list[dict], updated_at: str | None = None):
    return {
        "report_date": report_date,
        "title": f"日报 {report_date}",
        "summary": "",
        "updated_at": updated_at or f"{report_date}T08:00:00+00:00",
        "sections": {},
        "items": items,
        "article_count": len(items),
    }


def make_item(event_id: str, **overrides):
    item = {
        "event_id": event_id,
        "title": f"Event {event_id}",
        "category": "model_release",
        "tags": ["ai"],
        "final_score": 80.0,
        "published_at": "2026-07-08T06:00:00+00:00",
        "main_source": {"name": "OpenAI Blog", "url": "https://example.com", "tier": "T1"},
    }
    item.update(overrides)
    return item


class RangeHelperTests(unittest.TestCase):
    def test_week_range_covers_seven_days_ending_at_anchor(self):
        start, end = week_range(date(2026, 7, 9))

        self.assertEqual(start, date(2026, 7, 3))
        self.assertEqual(end, date(2026, 7, 9))

    def test_month_range_covers_calendar_month_of_anchor(self):
        start, end = month_range(date(2026, 7, 9))

        self.assertEqual(start, date(2026, 7, 1))
        self.assertEqual(end, date(2026, 7, 31))


class EventsPayloadTests(unittest.TestCase):
    def test_merges_daily_payloads_dedupes_by_event_id_keeping_newest_report(self):
        older = make_daily_payload(
            "2026-07-07",
            [make_item("evt-1", title="old title"), make_item("evt-2")],
        )
        newer = make_daily_payload(
            "2026-07-08",
            [make_item("evt-1", title="new title"), make_item("evt-3")],
        )

        payload = build_events_payload([older, newer])

        self.assertEqual(payload["total"], 3)
        titles = {item["event_id"]: item["title"] for item in payload["items"]}
        self.assertEqual(titles["evt-1"], "new title")
        self.assertEqual(payload["report_dates"], ["2026-07-07", "2026-07-08"])
        self.assertEqual(payload["updated_at"], "2026-07-08T08:00:00+00:00")

    def test_sorts_items_by_published_at_desc(self):
        payload = build_events_payload(
            [
                make_daily_payload(
                    "2026-07-08",
                    [
                        make_item("evt-early", published_at="2026-07-08T01:00:00+00:00"),
                        make_item("evt-late", published_at="2026-07-08T09:00:00+00:00"),
                    ],
                )
            ]
        )

        self.assertEqual(
            [item["event_id"] for item in payload["items"]],
            ["evt-late", "evt-early"],
        )

    def test_filters_by_category_and_query_and_paginates(self):
        items = [
            make_item("evt-1", category="research", title="LLM eval survey"),
            make_item("evt-2", category="model_release", title="New model ships"),
            make_item("evt-3", category="research", title="Vision paper"),
        ]
        daily = make_daily_payload("2026-07-08", items)

        by_category = build_events_payload([daily], category="research")
        self.assertEqual(by_category["total"], 2)

        by_query = build_events_payload([daily], q="llm")
        self.assertEqual(by_query["total"], 1)
        self.assertEqual(by_query["items"][0]["event_id"], "evt-1")

        paged = build_events_payload([daily], limit=1, offset=1)
        self.assertEqual(paged["total"], 3)
        self.assertEqual(len(paged["items"]), 1)

    def test_empty_payloads_produce_empty_contract(self):
        payload = build_events_payload([])

        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["items"], [])
        self.assertIsNone(payload["updated_at"])
        self.assertEqual(payload["report_dates"], [])


class PeriodPayloadTests(unittest.TestCase):
    def test_builds_weekly_payload_with_range_and_scored_items(self):
        payloads = [
            make_daily_payload("2026-07-07", [make_item("evt-1", final_score=70.0)]),
            make_daily_payload("2026-07-08", [make_item("evt-2", final_score=90.0)]),
        ]

        payload = build_period_payload(
            payloads,
            mode="weekly",
            range_start=date(2026, 7, 2),
            range_end=date(2026, 7, 8),
        )

        self.assertEqual(payload["mode"], "weekly")
        self.assertEqual(payload["range_start"], "2026-07-02")
        self.assertEqual(payload["range_end"], "2026-07-08")
        self.assertEqual(payload["article_count"], 2)
        self.assertEqual(
            [item["event_id"] for item in payload["items"]],
            ["evt-2", "evt-1"],
        )
        self.assertEqual(payload["report_dates"], ["2026-07-07", "2026-07-08"])


@unittest.skipIf(TestClient is None, "FastAPI is not installed in this environment")
class PublicEventRouteTests(unittest.TestCase):
    def _client(self, payloads_by_date):
        from app import main as module

        repository = FakeRepository(payloads_by_date)
        app = module.create_app(report_repository_factory=lambda: repository)
        return TestClient(app), repository

    def test_events_route_returns_merged_payload(self):
        client, repository = self._client(
            {
                date(2026, 7, 8): make_daily_payload(
                    "2026-07-08", [make_item("evt-1"), make_item("evt-2")]
                )
            }
        )

        response = client.get("/api/public/events")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 2)
        self.assertTrue(any(call.startswith("between:") for call in repository.calls))

    def test_events_route_validates_days(self):
        client, _ = self._client({})

        response = client.get("/api/public/events?days=0")

        self.assertEqual(response.status_code, 400)

    def test_weekly_route_returns_period_payload(self):
        client, _ = self._client(
            {
                date(2026, 7, 8): make_daily_payload(
                    "2026-07-08", [make_item("evt-1")]
                )
            }
        )

        response = client.get("/api/public/reports/weekly/2026-07-08")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["mode"], "weekly")
        self.assertEqual(body["range_start"], "2026-07-02")
        self.assertEqual(body["range_end"], "2026-07-08")
        self.assertEqual(body["article_count"], 1)

    def test_monthly_route_accepts_year_month(self):
        client, _ = self._client(
            {
                date(2026, 7, 8): make_daily_payload(
                    "2026-07-08", [make_item("evt-1")]
                )
            }
        )

        response = client.get("/api/public/reports/monthly/2026-07")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["mode"], "monthly")
        self.assertEqual(body["range_start"], "2026-07-01")
        self.assertEqual(body["range_end"], "2026-07-31")

    def test_monthly_route_rejects_bad_month(self):
        client, _ = self._client({})

        response = client.get("/api/public/reports/monthly/2026-13")

        self.assertEqual(response.status_code, 400)


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

    def get_daily_report_payloads_between(self, start_date, end_date):
        self.calls.append(f"between:{start_date.isoformat()}:{end_date.isoformat()}")
        return [
            payload
            for report_date, payload in sorted(self.payloads.items())
            if start_date <= report_date <= end_date
        ]


if __name__ == "__main__":
    unittest.main()

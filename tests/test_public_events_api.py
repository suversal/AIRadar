from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.api.public import (
    build_events_payload,
    build_period_payload,
    month_range,
    week_range,
)
from app.services.taxonomy import resolve_focus_category, source_filter_bucket

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

    def test_focus_filter_uses_explicit_focus_then_legacy_mapping(self):
        items = [
            make_item(
                "evt-1",
                category="product",
                scoring_category="product_release",
                focus_category="product",
                title="Product ships",
            ),
            make_item(
                "evt-2",
                category="model",
                scoring_category="open_source",
                focus_category="model",
                title="Open model weights",
            ),
            make_item("evt-3", category="model_release", title="New model"),
            make_item("evt-4", category="product", title="Already display-keyed"),
        ]
        daily = make_daily_payload("2026-07-08", items)

        payload = build_events_payload([daily], focus="product")

        self.assertEqual(payload["total"], 2)
        model_only = build_events_payload([daily], focus="model")
        self.assertEqual(model_only["total"], 2)

    def test_source_filter_runs_before_pagination(self):
        items = [
            make_item(
                "evt-official",
                main_source={
                    "name": "OpenAI Blog",
                    "url": "https://openai.com/news",
                    "tier": "T1",
                    "category": "official",
                },
            ),
            make_item(
                "evt-media",
                main_source={
                    "name": "TechCrunch",
                    "url": "https://techcrunch.com/ai",
                    "tier": "T2",
                    "category": "media",
                },
            ),
        ]

        payload = build_events_payload(
            [make_daily_payload("2026-07-08", items)],
            source="first_party",
            limit=1,
        )

        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["event_id"], "evt-official")

    def test_tag_filter_is_exact_and_distinct_from_keyword_search(self):
        items = [
            make_item(
                "evt-tagged",
                title="Frontier model release",
                tags=["OpenAI", "模型"],
            ),
            make_item(
                "evt-mentioned",
                title="Microsoft replaces OpenAI technology",
                tags=["Microsoft", "产品"],
            ),
        ]
        daily = make_daily_payload("2026-07-08", items)

        by_tag = build_events_payload([daily], tag="openai")
        by_keyword = build_events_payload([daily], q="OpenAI")

        self.assertEqual(by_tag["total"], 1)
        self.assertEqual(by_tag["items"][0]["event_id"], "evt-tagged")
        self.assertEqual(by_keyword["total"], 2)

    def test_topic_filter_narrows_events(self):
        items = [
            make_item("evt-1", title="OpenAI releases agent model"),
            make_item("evt-2", title="Claude 5 launches"),
            make_item("evt-3", title="随便聊聊"),
        ]
        daily = make_daily_payload("2026-07-08", items)

        payload = build_events_payload([daily], topic="anthropic")

        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["event_id"], "evt-2")

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

    def test_events_route_reads_processed_article_items_from_repository(self):
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
        self.assertTrue(
            any(call.startswith("all_items:") for call in repository.calls),
            f"expected all_items call, got {repository.calls}",
        )

    def test_event_detail_route_returns_single_event(self):
        client, _ = self._client({})

        found = client.get("/api/public/events/evt-known")
        missing = client.get("/api/public/events/evt-missing")

        self.assertEqual(found.status_code, 200)
        self.assertEqual(found.json()["event_id"], "evt-known")
        self.assertEqual(missing.status_code, 404)

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
        # a date key resolves to its ISO calendar week (matching VOL.YYYY-Www)
        self.assertEqual(body["period_key"], "2026-W28")
        self.assertEqual(body["range_start"], "2026-07-06")
        self.assertEqual(body["range_end"], "2026-07-12")
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

    def test_topics_route_returns_grouped_counts(self):
        client, _ = self._client(
            {
                date(2026, 7, 8): make_daily_payload(
                    "2026-07-08",
                    [
                        make_item("evt-1", title="OpenAI releases agent model"),
                        make_item("evt-2", title="Claude 5 launches"),
                    ],
                )
            }
        )

        response = client.get("/api/public/topics")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            [g["id"] for g in body["groups"]],
            ["models", "products", "directions", "companies"],
        )
        companies = {t["id"]: t["count"] for t in body["groups"][3]["topics"]}
        self.assertEqual(companies["openai"], 1)
        self.assertEqual(companies["anthropic"], 1)

    def test_events_route_accepts_topic_param(self):
        client, _ = self._client(
            {
                date(2026, 7, 8): make_daily_payload(
                    "2026-07-08",
                    [
                        make_item("evt-1", title="OpenAI releases agent model"),
                        make_item("evt-2", title="Claude 5 launches"),
                    ],
                )
            }
        )

        response = client.get("/api/public/events?topic=anthropic")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["event_id"], "evt-2")

    def test_events_route_filters_by_focus_before_pagination(self):
        client, _ = self._client(
            {
                date(2026, 7, 8): make_daily_payload(
                    "2026-07-08",
                    [
                        make_item(
                            "evt-1",
                            category="product",
                            scoring_category="open_source",
                            focus_category="model",
                        ),
                        make_item(
                            "evt-2",
                            category="product",
                            scoring_category="open_source",
                            focus_category="product",
                        ),
                    ],
                )
            }
        )

        response = client.get("/api/public/events?focus=model&limit=1")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["event_id"], "evt-1")

    def test_events_route_filters_by_source_before_pagination(self):
        client, _ = self._client(
            {
                date(2026, 7, 8): make_daily_payload(
                    "2026-07-08",
                    [
                        make_item(
                            "evt-official",
                            main_source={
                                "name": "OpenAI Blog",
                                "url": "https://openai.com/news",
                                "tier": "T1",
                                "category": "official",
                            },
                        ),
                        make_item(
                            "evt-media",
                            main_source={
                                "name": "TechCrunch",
                                "url": "https://techcrunch.com/ai",
                                "tier": "T2",
                                "category": "media",
                            },
                        ),
                    ],
                )
            }
        )

        response = client.get("/api/public/events?source=first_party&limit=1")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["event_id"], "evt-official")

    def test_events_route_filters_exact_tag_before_pagination(self):
        client, _ = self._client(
            {
                date(2026, 7, 8): make_daily_payload(
                    "2026-07-08",
                    [
                        make_item(
                            "evt-tagged",
                            title="Frontier model release",
                            tags=["OpenAI", "模型"],
                        ),
                        make_item(
                            "evt-mentioned",
                            title="Microsoft replaces OpenAI technology",
                            tags=["Microsoft", "产品"],
                        ),
                    ],
                )
            }
        )

        response = client.get("/api/public/events?tag=openai&limit=1")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["event_id"], "evt-tagged")

    def test_weekly_route_serves_persisted_report_by_key_and_date(self):
        client, repository = self._client(
            {
                date(2026, 7, 8): make_daily_payload(
                    "2026-07-08", [make_item("evt-1"), make_item("evt-2")]
                )
            }
        )
        repository.period_reports[("weekly", "2026-W28")] = {
            "kind": "weekly",
            "period_key": "2026-W28",
            "range_start": "2026-07-06",
            "range_end": "2026-07-12",
            "mainline_title": "AI 综述标题",
            "mainline_body": "AI 综述正文……",
            "theme_notes": [{"label": "模型", "note": "多家更新"}],
            "article_count": 12,
            "report_dates": ["2026-07-08"],
            "generated_at": "2026-07-10T08:00:00+00:00",
            "status": "generated",
        }

        by_key = client.get("/api/public/reports/weekly/2026-W28")
        by_date = client.get("/api/public/reports/weekly/2026-07-08")

        self.assertEqual(by_key.status_code, 200)
        body = by_key.json()
        self.assertTrue(body["generated"])
        self.assertEqual(body["period_key"], "2026-W28")
        self.assertEqual(body["mainline_title"], "AI 综述标题")
        self.assertEqual(len(body["items"]), 2)  # live items still attached
        self.assertEqual(by_date.json()["period_key"], "2026-W28")

    def test_weekly_route_hydrates_persisted_entries_to_live_content(self):
        client, repository = self._client({})
        repository.period_reports[("weekly", "2026-W28")] = {
            "kind": "weekly",
            "period_key": "2026-W28",
            "range_start": "2026-07-06",
            "range_end": "2026-07-12",
            "mainline_title": "AI 综述标题",
            "mainline_body": "AI 综述正文……",
            "theme_notes": [],
            "article_count": 2,
            "report_dates": ["2026-07-08"],
            "entries": [
                {"event_id": "evt-2", "score_at_selection": 95.0},
                {"event_id": "evt-1", "score_at_selection": 80.0},
                {"event_id": "evt-hidden", "score_at_selection": 70.0},
            ],
            "stats": {"source_coverage_count": 2, "multi_source_ratio": 0.5},
            "generated_at": "2026-07-10T08:00:00+00:00",
            "status": "generated",
        }
        # live content differs from whatever was true at generation time -
        # the snapshot only froze order/ids, not this title
        repository.event_items_by_id = {
            "evt-2": make_item("evt-2", title="标题已被后续更新"),
            "evt-1": make_item("evt-1"),
            # evt-hidden intentionally absent: simulates a moderated-away
            # event that the live resolver silently drops
        }

        response = client.get("/api/public/reports/weekly/2026-W28")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["generated"])
        # order frozen at generation time is preserved, hidden entry dropped
        self.assertEqual([item["event_id"] for item in body["items"]], ["evt-2", "evt-1"])
        self.assertEqual(body["items"][0]["title"], "标题已被后续更新")
        self.assertEqual(body["article_count"], 2)
        self.assertEqual(body["stats"]["source_coverage_count"], 2)

    def test_weekly_route_falls_back_when_no_persisted_report(self):
        client, _ = self._client(
            {
                date(2026, 7, 8): make_daily_payload(
                    "2026-07-08", [make_item("evt-1")]
                )
            }
        )

        response = client.get("/api/public/reports/weekly/2026-W28")

        body = response.json()
        self.assertFalse(body["generated"])
        self.assertEqual(body["period_key"], "2026-W28")
        self.assertEqual(body["article_count"], 1)

    def test_weekly_route_with_no_key_falls_back_to_latest_archived_period(self):
        # 2026-07-13 修复:同 /daily 的问题——本周(或本月)在还没有任何
        # 一次同步生成快照之前，硬套"今天所在的自然周期"会显示"等待
        # 生成"占位符。无 key 请求必须落到最近一个真正生成过快照的期次。
        import sys
        from pathlib import Path

        sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))
        from app.services.period_summary_service import period_key_for

        today = date.today()
        current_key = period_key_for("weekly", today)
        # 保证和当前自然周不是同一周
        archived_key = period_key_for("weekly", today - timedelta(days=14))

        client, repository = self._client({})
        repository.period_archive["weekly"] = [
            {
                "period_key": archived_key,
                "range_start": "2000-01-01",
                "range_end": "2000-01-07",
                "mainline_title": "已归档的一期",
                "article_count": 5,
            },
        ]
        # 当前自然周没有持久化快照(current_key 不在 period_reports 里)
        self.assertNotIn(("weekly", current_key), repository.period_reports)

        response = client.get("/api/public/reports/weekly")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["period_key"], archived_key)

    def test_period_archive_routes(self):
        client, repository = self._client({})
        repository.period_archive["weekly"] = [
            {"period_key": "2026-W28", "range_start": "2026-07-06", "range_end": "2026-07-12", "mainline_title": "标题", "article_count": 12},
        ]
        repository.daily_dates = ["2026-07-10", "2026-07-09"]

        weekly = client.get("/api/public/reports/weekly/archive")
        daily = client.get("/api/public/reports/daily/archive")

        self.assertEqual(weekly.status_code, 200)
        self.assertEqual(weekly.json()["entries"][0]["period_key"], "2026-W28")
        self.assertEqual(daily.json()["dates"], ["2026-07-10", "2026-07-09"])

    def test_monthly_route_rejects_bad_month(self):
        client, _ = self._client({})

        response = client.get("/api/public/reports/monthly/2026-13")

        self.assertEqual(response.status_code, 400)


class FakeRepository:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []
        self.period_reports = {}
        self.period_archive = {}
        self.daily_dates = []
        self.event_items_by_id = {}

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

    def get_all_event_items_between(self, start_date, end_date):
        self.calls.append(f"all_items:{start_date.isoformat()}:{end_date.isoformat()}")
        items = []
        for report_date, payload in sorted(self.payloads.items()):
            if start_date <= report_date <= end_date:
                items.extend(payload.get("items", []))
        return items

    def count_and_get_all_event_items_between(
        self,
        start_date,
        end_date,
        *,
        category=None,
        source=None,
        limit=50,
        offset=0,
    ):
        self.calls.append(f"count_all_items:{start_date.isoformat()}:{end_date.isoformat()}")
        items = self.get_all_event_items_between(start_date, end_date)
        if category:
            items = [
                item
                for item in items
                if resolve_focus_category(
                    item.get("focus_category"),
                    item.get("scoring_category") or item.get("category"),
                )
                == category
            ]
        if source:
            items = [
                item
                for item in items
                if source_filter_bucket((item.get("main_source") or {}).get("category"))
                == source
            ]
        items = sorted(items, key=lambda item: str(item.get("published_at") or ""), reverse=True)
        total = len(items)
        updated_at = items[0]["published_at"] if items else None
        return items[offset : offset + limit], total, updated_at

    def get_event_item(self, event_id):
        self.calls.append(f"event:{event_id}")
        if event_id == "evt-known":
            return make_item("evt-known")
        return None

    def get_event_items_by_ids(self, event_ids):
        self.calls.append(f"items_by_ids:{','.join(event_ids)}")
        # mirrors the real repository: preserve order, silently skip
        # ids that don't resolve (hidden or gone)
        return [
            self.event_items_by_id[event_id]
            for event_id in event_ids
            if event_id in self.event_items_by_id
        ]

    period_reports: dict = {}
    period_archive: dict = {}
    daily_dates: list = []

    def get_period_report(self, kind, period_key):
        return self.period_reports.get((kind, period_key))

    def list_period_reports(self, kind, limit=24):
        return list(self.period_archive.get(kind, []))

    def list_daily_report_dates(self, limit=90):
        return list(self.daily_dates)


if __name__ == "__main__":
    unittest.main()

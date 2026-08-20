from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.api.public import (
    build_latest_selected_payload_from_repository,
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
        "selected": True,
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


class SlimPeriodItemsTests(unittest.TestCase):
    """周月报对外负载剥掉文章正文。

    实测一份月报 476 条、16.6 MB，其中正文字段占 96%，而页面一个都不用
    （只渲染标题/理由/标签/来源数，且每个板块只展示前 3 条）。
    剥掉后降到 1.1 MB，也就重新落回 Next 数据缓存 2MB 上限之内。
    见 docs/2026-08-13-hardening-plan.md 附录。"""

    def _item(self):
        return {
            "event_id": "evt-1",
            "title": "标题",
            "summary": "摘要",
            "reason": "推荐理由",
            "tags": ["ai"],
            "source_count": 3,
            "main_source": {"name": "来源", "url": "https://example.com", "tier": "t1"},
            "focus_category": "tutorial",
            "scoring_category": "tutorial",
            "selected": True,
            "one_line_summary": "一句话",
            "original_content": "正文" * 5000,
            "original_blocks": [{"type": "paragraph", "text": "段落"}],
            "original_paragraphs": ["段落"],
            "original_images": [{"url": "https://example.com/a.png"}],
            "original_markdown": "# 标题",
            "translated_content": "译文" * 5000,
            "translated_blocks": [{"type": "paragraph", "text": "译文段"}],
            "translated_paragraphs": ["译文段"],
        }

    def test_strips_article_bodies_but_keeps_everything_the_page_renders(self):
        from app.api.public import slim_period_items

        slimmed = slim_period_items([self._item()])[0]

        for dropped in (
            "original_content",
            "original_blocks",
            "original_paragraphs",
            "original_images",
            "original_markdown",
            "translated_content",
            "translated_blocks",
            "translated_paragraphs",
        ):
            self.assertNotIn(dropped, slimmed, f"{dropped} 应该被剥掉")

        # 周月报页面与 buildPeriodDigest 实际用到的字段，一个都不能少
        for kept in (
            "event_id",
            "title",
            "summary",
            "reason",
            "tags",
            "source_count",
            "main_source",
            "focus_category",
            "scoring_category",
            "selected",
            "one_line_summary",
        ):
            self.assertIn(kept, slimmed, f"{kept} 是页面要渲染的，不能剥")

    def test_is_a_denylist_so_new_fields_survive(self):
        """用"剥掉哪些"而不是"保留哪些"：将来给事件加了新字段，
        页面能直接用上，不会因为忘了加白名单而神秘地读不到值。"""
        from app.api.public import slim_period_items

        item = self._item()
        item["some_future_field"] = "新加的"

        self.assertEqual(slim_period_items([item])[0]["some_future_field"], "新加的")

    def test_handles_items_missing_the_heavy_fields(self):
        from app.api.public import slim_period_items

        self.assertEqual(
            slim_period_items([{"event_id": "evt-1", "title": "标题"}]),
            [{"event_id": "evt-1", "title": "标题"}],
        )


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

    def _current_payloads(self, items):
        today = date.today()
        return {today: make_daily_payload(today.isoformat(), items)}

    def test_events_route_reads_processed_article_items_from_repository(self):
        client, repository = self._client(
            self._current_payloads([make_item("evt-1"), make_item("evt-2")])
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
            self._current_payloads(
                [
                    make_item("evt-1", title="OpenAI releases agent model"),
                    make_item("evt-2", title="Claude 5 launches"),
                    # 未精选的条目不计入索引页(卡片写的是"精选 N 条")
                    make_item("evt-3", title="Claude rumor roundup", selected=False),
                ]
            )
        )

        response = client.get("/api/public/topics")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([g["id"] for g in body["groups"]], ["entities", "directions"])
        entities = {t["id"]: t for t in body["groups"][0]["topics"]}
        self.assertEqual(entities["openai"]["count"], 1)
        self.assertEqual(entities["anthropic"]["count"], 1)
        self.assertTrue(entities["anthropic"]["description"])
        self.assertEqual(body["article_count"], 2)
        # 没有故事线数据时字段也必须在,前端不做 undefined 分支
        self.assertEqual(body["storylines"], [])

    def test_topics_route_returns_shaped_storylines(self):
        from datetime import datetime, timezone

        client, repository = self._client(
            self._current_payloads([make_item("evt-1", title="Claude 5 launches")])
        )
        repository.storylines = [
            {
                "event_id": "story-1",
                "title": "某事件持续发酵",
                "source_count": 4,
                "first_seen_at": datetime(2026, 8, 17, 1, tzinfo=timezone.utc),
                "last_seen_at": datetime(2026, 8, 19, 1, tzinfo=timezone.utc),
            },
            {
                # 同一天 → 被跨天过滤挡掉
                "event_id": "same-day",
                "title": "单日热点",
                "source_count": 9,
                "first_seen_at": datetime(2026, 8, 19, 1, tzinfo=timezone.utc),
                "last_seen_at": datetime(2026, 8, 19, 5, tzinfo=timezone.utc),
            },
        ]

        response = client.get("/api/public/topics")

        self.assertEqual(response.status_code, 200)
        storylines = response.json()["storylines"]
        self.assertEqual([s["event_id"] for s in storylines], ["story-1"])
        self.assertEqual(storylines[0]["days"], 3)
        self.assertEqual(storylines[0]["source_count"], 4)

    def test_topic_detail_route_returns_header_and_timeline(self):
        client, _ = self._client(
            self._current_payloads(
                [
                    make_item("evt-1", title="Claude 5 launches"),
                    make_item("evt-2", title="Claude rumor roundup", selected=False),
                    make_item("evt-3", title="OpenAI releases agent model"),
                ]
            )
        )

        response = client.get("/api/public/topics/anthropic")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["topic"]["id"], "anthropic")
        self.assertEqual(body["topic"]["group_id"], "entities")
        # 收录含未精选,时间线只放精选
        self.assertEqual(body["total_count"], 2)
        self.assertEqual(body["selected_count"], 1)
        self.assertEqual([item["event_id"] for item in body["items"]], ["evt-1"])

    def test_topic_detail_route_resolves_legacy_alias_and_rejects_unknown(self):
        client, _ = self._client(
            self._current_payloads([make_item("evt-1", title="Claude 5 launches")])
        )

        # 旧版四组时代的 id(claude)重定向到合并后的实体主题
        response = client.get("/api/public/topics/claude")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["topic"]["id"], "anthropic")

        self.assertEqual(client.get("/api/public/topics/nope").status_code, 404)

    def test_events_route_accepts_topic_param(self):
        client, _ = self._client(
            self._current_payloads(
                [
                    make_item("evt-1", title="OpenAI releases agent model"),
                    make_item("evt-2", title="Claude 5 launches"),
                ]
            )
        )

        response = client.get("/api/public/events?topic=anthropic")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["event_id"], "evt-2")

    def test_events_route_filters_by_focus_before_pagination(self):
        client, _ = self._client(
            self._current_payloads(
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
                ]
            )
        )

        response = client.get("/api/public/events?focus=model&limit=1")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["event_id"], "evt-1")

    def test_events_route_filters_by_source_before_pagination(self):
        client, _ = self._client(
            self._current_payloads(
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
                ]
            )
        )

        response = client.get("/api/public/events?source=first_party&limit=1")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["event_id"], "evt-official")

    def test_events_route_filters_exact_tag_before_pagination(self):
        client, _ = self._client(
            self._current_payloads(
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
                ]
            )
        )

        response = client.get("/api/public/events?tag=openai&limit=1")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["event_id"], "evt-tagged")

    def test_telegram_route_lists_active_rsshub_channels_and_filters_articles(self):
        today = date.today()
        client, repository = self._client(
            {
                today: make_daily_payload(
                    today.isoformat(),
                    [
                        make_item(
                            "evt-zaihua",
                            main_source={
                                "id": "telegram_zaihuapd",
                                "name": "在花频道",
                                "url": "https://t.me/zaihuapd/1",
                                "tier": "T3",
                                "category": "community",
                            },
                        ),
                        make_item(
                            "evt-loopdns",
                            main_source={
                                "id": "telegram_dnspodt",
                                "name": "LoopDNS 资讯播报",
                                "url": "https://t.me/DNSPODT/2",
                                "tier": "T3",
                                "category": "community",
                            },
                        ),
                        make_item(
                            "evt-official",
                            main_source={
                                "id": "openai_blog",
                                "name": "OpenAI Blog",
                                "url": "https://openai.com/news",
                                "tier": "T1",
                                "category": "official",
                            },
                        ),
                    ],
                )
            }
        )
        repository.sources = [
            SimpleNamespace(
                id="telegram_zaihuapd",
                name="在花频道",
                type="telegram_rss",
                is_active=True,
                homepage="https://t.me/zaihuapd",
                config={"channel": "zaihuapd"},
            ),
            SimpleNamespace(
                id="telegram_dnspodt",
                name="LoopDNS 资讯播报",
                type="telegram_rss",
                is_active=True,
                homepage="https://t.me/DNSPODT",
                config={"channel": "DNSPODT"},
            ),
            SimpleNamespace(
                id="telegram_disabled",
                name="停用频道",
                type="telegram_rss",
                is_active=False,
                homepage="https://t.me/disabled",
                config={"channel": "disabled"},
            ),
            SimpleNamespace(
                id="openai_blog",
                name="OpenAI Blog",
                type="rss",
                is_active=True,
                homepage="https://openai.com",
                config={},
            ),
        ]

        all_response = client.get("/api/public/telegram")
        response = client.get("/api/public/telegram?channel=telegram_zaihuapd")

        self.assertEqual(all_response.status_code, 200)
        self.assertEqual(all_response.json()["total"], 2)
        self.assertEqual(
            {item["event_id"] for item in all_response.json()["items"]},
            {"evt-zaihua", "evt-loopdns"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["event_id"], "evt-zaihua")
        self.assertEqual(
            {channel["id"] for channel in body["channels"]},
            {"telegram_zaihuapd", "telegram_dnspodt"},
        )

    def test_telegram_route_rejects_unknown_channel(self):
        client, repository = self._client({})
        repository.sources = []

        response = client.get("/api/public/telegram?channel=not-configured")

        self.assertEqual(response.status_code, 400)

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
        self.sources = []

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

    def get_all_event_items_between(self, start_date, end_date, *, selected_only=False):
        self.calls.append(f"all_items:{start_date.isoformat()}:{end_date.isoformat()}")
        items = []
        for report_date, payload in sorted(self.payloads.items()):
            if start_date <= report_date <= end_date:
                items.extend(payload.get("items", []))
        if selected_only:
            items = [item for item in items if item.get("selected")]
        return items

    def get_active_storylines(self, *, since, limit=20):
        self.calls.append("storylines")
        return list(getattr(self, "storylines", []))

    def count_and_get_all_event_items_between(
        self,
        start_date,
        end_date,
        *,
        category=None,
        source=None,
        source_ids=None,
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
        if source_ids is not None:
            items = [
                item
                for item in items
                if (item.get("main_source") or {}).get("id") in source_ids
            ]
        items = sorted(items, key=lambda item: str(item.get("published_at") or ""), reverse=True)
        total = len(items)
        updated_at = items[0]["published_at"] if items else None
        return items[offset : offset + limit], total, updated_at

    def get_all_sources(self):
        return list(self.sources)

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


class LatestSelectedFeedTests(unittest.TestCase):
    """精选流按事件去重：一个事件只出它的代表条。

    2026-08-18：在此之前 selected_only 放行的是"所属簇里有人入选"，同一
    事件的每个成员都各自成卡——包括自己 0 分被淘汰的那些，再被 /latest 的
    alwaysSelected 盖上"精选"章，于是页面上出现"0 分的精选"。
    """

    @staticmethod
    def _repository(items):
        def get_all_event_items_between(start_date, end_date, selected_only=False):
            return list(items)

        return SimpleNamespace(get_all_event_items_between=get_all_event_items_between)

    def test_non_main_cluster_members_stay_out_of_the_selected_feed(self):
        items = [
            {
                "event_id": "c1",
                "is_main": True,
                "final_score": 72.0,
                "source_count": 3,
                "published_at": "2026-08-18T09:00:00+00:00",
            },
            {
                "event_id": "a0000000000a",
                "is_main": False,
                "final_score": 0.0,
                "source_count": 3,
                "published_at": "2026-08-18T08:30:00+00:00",
            },
            {
                "event_id": "a0000000000b",
                "is_main": False,
                "final_score": 0.0,
                "source_count": 3,
                "published_at": "2026-08-18T08:00:00+00:00",
            },
        ]

        payload = build_latest_selected_payload_from_repository(
            self._repository(items), end_date=date(2026, 8, 18)
        )

        self.assertEqual([item["event_id"] for item in payload["items"]], ["c1"])
        self.assertEqual(payload["total"], 1)

    def test_standalone_articles_without_a_cluster_still_show_up(self):
        # 没有聚类的孤条压根没有 is_main 字段，不能被去重误伤
        items = [
            {
                "event_id": "a0000000000c",
                "final_score": 64.0,
                "source_count": 1,
                "published_at": "2026-08-18T07:00:00+00:00",
            }
        ]

        payload = build_latest_selected_payload_from_repository(
            self._repository(items), end_date=date(2026, 8, 18)
        )

        self.assertEqual([item["event_id"] for item in payload["items"]], ["a0000000000c"])


if __name__ == "__main__":
    unittest.main()

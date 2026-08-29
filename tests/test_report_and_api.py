import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.api.public import (
    build_daily_payload,
    build_daily_payload_from_repository,
    build_hotspots_payload,
    build_latest_payload,
    build_latest_payload_from_repository,
)
from app.models.domain import ContentValueDimensions, EventCluster, ProcessedArticle, RawArticle, Source
from app.services.daily_report_service import build_daily_json, render_daily_markdown


class ReportAndAPITests(unittest.TestCase):
    def setUp(self):
        self.article = RawArticle(
            id="a1",
            source_id="openai_blog",
            source_name="OpenAI Blog",
            source_role="authority",
            source_tier="T1",
            source_url="https://openai.com/a",
            title="OpenAI releases agent model",
            content="AI model release",
            author=None,
            published_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
            language="en",
            raw_score={},
            metadata={
                "original_text": "OpenAI 发布新的 Agent 模型。\n\n开发者可以用它构建自动化工作流。",
                "original_markdown": "# OpenAI Agent\n\n开发者可以用它构建自动化工作流。",
                "readme_name": "README_CN.md",
                "readme_language": "zh",
                "readme_selection": "preferred_zh_readme",
                "original_paragraphs": [
                    "OpenAI 发布新的 Agent 模型。",
                    "开发者可以用它构建自动化工作流。",
                ],
                "original_images": [
                    {
                        "url": "https://openai.com/agent.png",
                        "alt": "Agent model diagram",
                        "caption": "",
                    }
                ],
                "original_blocks": [
                    {"type": "paragraph", "text": "OpenAI 发布新的 Agent 模型。"},
                    {
                        "type": "image",
                        "url": "https://openai.com/agent.png",
                        "alt": "Agent model diagram",
                        "caption": "",
                    },
                    {"type": "paragraph", "text": "开发者可以用它构建自动化工作流。"},
                ],
                "translated_paragraphs": [
                    "OpenAI 发布新的 Agent 模型。",
                    "开发者可以用它构建自动化工作流。",
                ],
                "translated_blocks": [
                    {"type": "paragraph", "text": "OpenAI 发布新的 Agent 模型。"},
                    {
                        "type": "image",
                        "url": "https://openai.com/agent.png",
                        "alt": "Agent model diagram",
                        "caption": "",
                    },
                    {"type": "paragraph", "text": "开发者可以用它构建自动化工作流。"},
                ],
            },
            title_hash="t",
            url_hash="u",
        )
        self.processed = ProcessedArticle(
            raw_article_id="a1",
            event_cluster_id="c1",
            ai_focus="primary",
            dimensions=ContentValueDimensions(impact=8, novelty=8, substance=8),
            final_score=92.0,
            title_zh="OpenAI 发布 Agent 模型",
            one_line_summary="OpenAI 发布新的 Agent 模型。",
            summary_zh="OpenAI 发布新的 Agent 模型。",
            reason_zh="这会影响开发者构建 Agent 的方式。",
            action_zh="阅读官方发布并评估 API 变化。",
            category="model_release",
            tags=["Agent", "OpenAI"],
            selected=True,
            status="processed",
        )
        self.cluster = EventCluster(
            id="c1",
            main_article_id="a1",
            article_ids=["a1"],
            event_title="OpenAI 发布 Agent 模型",
            event_summary="OpenAI 发布新的 Agent 模型。",
            category="model_release",
            tags=["Agent", "OpenAI"],
            final_score=92.0,
            source_count=1,
            first_seen_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
            last_seen_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
        )
        self.source = Source(
            id="openai_blog",
            name="OpenAI Blog",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://openai.com/rss.xml",
            homepage="https://openai.com",
            allowed_domains=["openai.com"],
            can_be_main_source=True,
        )

    def test_render_daily_markdown_contains_required_editorial_fields(self):
        markdown = render_daily_markdown(
            report_date=date(2026, 7, 1),
            clusters=[self.cluster],
            processed_by_article={"a1": self.processed},
            articles_by_id={"a1": self.article},
            sources_by_id={"openai_blog": self.source},
        )

        self.assertIn("# Suversal AI Radar 日报 - 2026-07-01", markdown)
        self.assertIn("为什么重要", markdown)
        self.assertIn("下一步", markdown)
        self.assertIn("OpenAI Blog", markdown)

    def test_render_daily_markdown_includes_ai_core_summary(self):
        self.processed.summary_zh = "核心总结保留模型能力、适用对象和关键上下文。"

        markdown = render_daily_markdown(
            report_date=date(2026, 7, 1),
            clusters=[self.cluster],
            processed_by_article={"a1": self.processed},
            articles_by_id={"a1": self.article},
            sources_by_id={"openai_blog": self.source},
        )

        self.assertIn("- 核心总结：核心总结保留模型能力、适用对象和关键上下文。", markdown)

    def test_daily_json_and_public_payloads_match_contract(self):
        generated_at = datetime(2026, 7, 7, 14, 30, tzinfo=timezone.utc)
        daily_json = build_daily_json(
            report_date=date(2026, 7, 1),
            clusters=[self.cluster],
            processed_by_article={"a1": self.processed},
            articles_by_id={"a1": self.article},
            sources_by_id={"openai_blog": self.source},
            generated_at=generated_at,
        )
        latest = build_latest_payload(daily_json)
        daily = build_daily_payload(daily_json)

        self.assertEqual(latest["report_date"], "2026-07-01")
        self.assertEqual(latest["updated_at"], "2026-07-07T14:30:00+00:00")
        self.assertEqual(daily["latest_published_at"], "2026-07-01T09:00:00+00:00")
        self.assertEqual(latest["items"][0]["event_id"], "c1")
        # entries resolution (daily_report_entries) needs this to resolve
        # items live instead of trusting the frozen snapshot
        self.assertEqual(latest["items"][0]["raw_article_id"], "a1")
        self.assertEqual(latest["items"][0]["main_source"]["name"], "OpenAI Blog")
        self.assertEqual(
            latest["items"][0]["original_paragraphs"],
            ["OpenAI 发布新的 Agent 模型。", "开发者可以用它构建自动化工作流。"],
        )
        self.assertEqual(latest["items"][0]["original_images"][0]["url"], "https://openai.com/agent.png")
        self.assertEqual(latest["items"][0]["original_blocks"][1]["type"], "image")
        self.assertEqual(
            latest["items"][0]["original_markdown"],
            "# OpenAI Agent\n\n开发者可以用它构建自动化工作流。",
        )
        self.assertEqual(latest["items"][0]["readme_name"], "README_CN.md")
        self.assertEqual(latest["items"][0]["readme_language"], "zh")
        self.assertEqual(latest["items"][0]["readme_selection"], "preferred_zh_readme")
        self.assertEqual(latest["items"][0]["source_language"], "en")
        self.assertEqual(
            latest["items"][0]["translated_paragraphs"],
            ["OpenAI 发布新的 Agent 模型。", "开发者可以用它构建自动化工作流。"],
        )
        self.assertEqual(latest["items"][0]["translated_blocks"][1]["type"], "image")
        self.assertEqual(daily["report_date"], "2026-07-01")

    def test_daily_json_items_and_sections_use_display_taxonomy(self):
        daily_json = build_daily_json(
            report_date=date(2026, 7, 1),
            clusters=[self.cluster],
            processed_by_article={"a1": self.processed},
            articles_by_id={"a1": self.article},
            sources_by_id={"openai_blog": self.source},
            generated_at=datetime(2026, 7, 7, 14, 30, tzinfo=timezone.utc),
        )

        item = daily_json["items"][0]
        # self.processed has scoring category model_release
        self.assertEqual(item["category"], "model")
        self.assertEqual(item["category_label"], "模型")
        self.assertEqual(item["scoring_category"], "model_release")
        self.assertEqual(item["focus_category"], "model")
        self.assertEqual(item["focus_category_label"], "模型动态")
        # sections now group by focus_category, not the legacy display category
        self.assertEqual(list(daily_json["sections"].keys()), ["model"])

    def test_daily_json_sections_group_by_focus_not_display_category(self):
        # opinion (category axis) maps to display "tutorial" but, once the
        # text carries a clear model signal, resolves to focus "model" - a
        # fixture where the two taxonomies disagree, so the section key
        # actually proves which axis build_daily_json groups by.
        self.processed.category = "opinion"
        self.cluster.category = "opinion"
        self.processed.summary_zh = "关于下一代基础模型路线的分析与预测。"
        self.processed.one_line_summary = "模型路线观点分析。"

        daily_json = build_daily_json(
            report_date=date(2026, 7, 1),
            clusters=[self.cluster],
            processed_by_article={"a1": self.processed},
            articles_by_id={"a1": self.article},
            sources_by_id={"openai_blog": self.source},
            generated_at=datetime(2026, 7, 7, 14, 30, tzinfo=timezone.utc),
        )

        item = daily_json["items"][0]
        self.assertEqual(item["category"], "tutorial")
        self.assertEqual(item["focus_category"], "model")
        self.assertEqual(list(daily_json["sections"].keys()), ["model"])

    def test_daily_json_preserves_inline_html_on_paragraph_blocks(self):
        self.article.metadata["original_blocks"] = [
            {
                "type": "paragraph",
                "text": "Read the full paper for key results.",
                "html": 'Read the <a href="https://example.com/p">full paper</a> for <strong>key results</strong>.',
            },
        ]
        daily_json = build_daily_json(
            report_date=date(2026, 7, 1),
            clusters=[self.cluster],
            processed_by_article={"a1": self.processed},
            articles_by_id={"a1": self.article},
            sources_by_id={"openai_blog": self.source},
            generated_at=datetime(2026, 7, 7, 14, 30, tzinfo=timezone.utc),
        )

        block = daily_json["items"][0]["original_blocks"][0]
        self.assertIn("<strong>key results</strong>", block["html"])

    def test_daily_json_exposes_translation_failure_status(self):
        self.article.metadata.pop("translated_paragraphs", None)
        self.article.metadata.pop("translated_blocks", None)
        self.article.metadata["translation_status"] = "failed"
        self.article.metadata["translation_error"] = "Chat response was not valid JSON"
        daily_json = build_daily_json(
            report_date=date(2026, 7, 1),
            clusters=[self.cluster],
            processed_by_article={"a1": self.processed},
            articles_by_id={"a1": self.article},
            sources_by_id={"openai_blog": self.source},
            generated_at=datetime(2026, 7, 7, 14, 30, tzinfo=timezone.utc),
        )

        item = daily_json["items"][0]
        self.assertEqual(item["translation_status"], "failed")
        self.assertEqual(item["translation_error"], "Chat response was not valid JSON")

    def test_public_payloads_can_be_loaded_from_repository(self):
        repository = FakeDailyReportRepository(
            {
                date(2026, 7, 1): {
                    "report_date": "2026-07-01",
                    "title": "Suversal AI Radar 日报 - 2026-07-01",
                    "summary": "精选 1 条 AI 情报。",
                    "updated_at": "2026-07-01T09:00:00+00:00",
                    "sections": {"model_release": []},
                    "items": [{"event_id": "c1"}],
                    "article_count": 1,
                }
            }
        )

        latest = build_latest_payload_from_repository(repository)
        daily = build_daily_payload_from_repository(repository, date(2026, 7, 1))

        self.assertEqual(latest["report_date"], "2026-07-01")
        self.assertEqual(latest["items"][0]["event_id"], "c1")
        self.assertEqual(daily["report_date"], "2026-07-01")
        self.assertEqual(repository.calls, ["latest", "daily:2026-07-01"])

    def test_public_repository_payloads_return_empty_shape_when_missing(self):
        repository = FakeDailyReportRepository({})

        latest = build_latest_payload_from_repository(repository)
        daily = build_daily_payload_from_repository(repository, date(2026, 7, 3))

        self.assertIsNone(latest["report_date"])
        self.assertEqual(latest["items"], [])
        self.assertIsNone(latest["updated_at"])
        self.assertEqual(daily["report_date"], "2026-07-03")
        self.assertEqual(daily["article_count"], 0)
        self.assertEqual(daily["items"], [])


class HotspotPayloadTests(unittest.TestCase):
    NOW = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)

    def _item(
        self,
        event_id,
        *,
        sources=1,
        score=50.0,
        hours_ago=1,
        last_seen_hours_ago=None,
        category="model",
        title=None,
        is_main=True,
    ):
        published = self.NOW - timedelta(hours=hours_ago)
        item = {
            "event_id": event_id,
            "title": title or f"event {event_id}",
            "category": category,
            "tags": [],
            "final_score": score,
            "source_count": sources,
            "published_at": published.isoformat(),
            "is_main": is_main,
        }
        if last_seen_hours_ago is not None:
            item["last_seen_at"] = (
                self.NOW - timedelta(hours=last_seen_hours_ago)
            ).isoformat()
        return item

    def test_multi_source_events_rank_before_high_score_singles(self):
        items = [
            self._item("d", sources=1, score=99),
            self._item("a", sources=3, score=80),
            self._item("e", sources=1, score=90),
            self._item("b", sources=5, score=70),
            self._item("f", sources=1, score=85),
            self._item("c", sources=2, score=95),
        ]
        payload = build_hotspots_payload(items, now=self.NOW)
        self.assertEqual(
            [item["event_id"] for item in payload["items"]],
            ["b", "a", "c", "d", "e"],
        )

    def test_equal_source_count_breaks_tie_by_score(self):
        items = [
            self._item("low", sources=2, score=60),
            self._item("high", sources=2, score=90),
        ]
        payload = build_hotspots_payload(items, now=self.NOW)
        self.assertEqual(
            [item["event_id"] for item in payload["items"]], ["high", "low"]
        )

    def test_lifetime_coverage_does_not_inflate_window_ranking(self):
        old_burst = self._item("old-burst", sources=8, score=90)
        old_burst.update(window_report_count=4, window_source_count=4)
        current_burst = self._item("current-burst", sources=5, score=70)
        current_burst.update(window_report_count=5, window_source_count=5)

        payload = build_hotspots_payload(
            [old_burst, current_burst], now=self.NOW
        )

        self.assertEqual(
            [item["event_id"] for item in payload["items"]],
            ["current-burst", "old-burst"],
        )

    def test_window_report_count_leads_then_window_source_count(self):
        more_reports = self._item("more-reports", sources=9, score=60)
        more_reports.update(window_report_count=5, window_source_count=2)
        more_sources = self._item("more-sources", sources=9, score=99)
        more_sources.update(window_report_count=4, window_source_count=4)

        payload = build_hotspots_payload(
            [more_sources, more_reports], now=self.NOW
        )

        self.assertEqual(
            [item["event_id"] for item in payload["items"]],
            ["more-reports", "more-sources"],
        )

    def test_whole_day_window_matches_relative_calendar_day_labels(self):
        items = [
            self._item("two-days-ago", sources=6, score=99, hours_ago=54),
            self._item("yesterday", sources=2, score=10, hours_ago=34),
        ]
        payload = build_hotspots_payload(items, now=self.NOW)
        self.assertEqual(
            [item["event_id"] for item in payload["items"]], ["yesterday"]
        )

    def test_last_seen_at_keeps_old_event_with_fresh_coverage(self):
        items = [
            self._item("revived", sources=3, score=70, hours_ago=72, last_seen_hours_ago=2),
        ]
        payload = build_hotspots_payload(items, now=self.NOW)
        self.assertEqual(
            [item["event_id"] for item in payload["items"]], ["revived"]
        )

    def test_all_single_source_falls_back_to_score_order(self):
        items = [
            self._item("mid", sources=1, score=80),
            self._item("top", sources=1, score=95),
            self._item("low", sources=1, score=60),
        ]
        payload = build_hotspots_payload(items, now=self.NOW)
        self.assertEqual(
            [item["event_id"] for item in payload["items"]],
            ["top", "mid", "low"],
        )

    def test_limit_caps_the_board_at_five_by_default(self):
        items = [
            self._item(f"e{index}", sources=2, score=50 + index)
            for index in range(8)
        ]
        payload = build_hotspots_payload(items, now=self.NOW)
        self.assertEqual(len(payload["items"]), 5)

    def test_category_and_query_filters_apply_before_ranking(self):
        items = [
            self._item("model-multi", sources=4, score=70, category="model"),
            self._item("product-multi", sources=5, score=90, category="product"),
            self._item("model-single", sources=1, score=95, category="model"),
        ]
        payload = build_hotspots_payload(items, category="model", now=self.NOW)
        self.assertEqual(
            [item["event_id"] for item in payload["items"]],
            ["model-multi", "model-single"],
        )
        query_payload = build_hotspots_payload(
            items, q="product-multi", now=self.NOW
        )
        self.assertEqual(
            [item["event_id"] for item in query_payload["items"]],
            ["product-multi"],
        )

    def test_tag_filter_is_exact_before_hotspot_ranking(self):
        tagged = self._item("tagged", sources=2, score=70)
        tagged["tags"] = ["OpenAI", "模型"]
        mentioned = self._item(
            "mentioned",
            sources=3,
            score=90,
            title="Microsoft replaces OpenAI technology",
        )
        mentioned["tags"] = ["Microsoft", "产品"]

        payload = build_hotspots_payload(
            [tagged, mentioned],
            tag="openai",
            now=self.NOW,
        )

        self.assertEqual(
            [item["event_id"] for item in payload["items"]],
            ["tagged"],
        )

    def test_hidden_items_never_reach_the_board(self):
        hidden = self._item("hidden", sources=5, score=99)
        hidden["hidden"] = True
        items = [hidden, self._item("visible", sources=2, score=50)]
        payload = build_hotspots_payload(items, now=self.NOW)
        self.assertEqual(
            [item["event_id"] for item in payload["items"]], ["visible"]
        )

    def test_non_main_cluster_members_never_reach_the_board(self):
        # 2026-07-13:/all 和后台不再去重，同一事件的多个成员会作为独立
        # item 出现在候选池里；热点榜必须只把 is_main 的那条当候选，
        # 否则一个 4 信源事件会用 4 条重复记录挤满前 5 名
        main = self._item("e-multi", sources=4, score=70, is_main=True)
        member_a = self._item("a-member1", sources=4, score=68, is_main=False)
        member_b = self._item("a-member2", sources=4, score=65, is_main=False)
        others = [self._item(f"single{i}", sources=1, score=90 - i) for i in range(4)]
        items = [main, member_a, member_b, *others]

        payload = build_hotspots_payload(items, now=self.NOW)

        event_ids = [item["event_id"] for item in payload["items"]]
        self.assertIn("e-multi", event_ids)
        self.assertNotIn("a-member1", event_ids)
        self.assertNotIn("a-member2", event_ids)
        self.assertEqual(len(payload["items"]), 5)

    def test_empty_items_produce_empty_payload(self):
        payload = build_hotspots_payload([], now=self.NOW)
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["item_count"], 0)
        self.assertEqual(payload["window_hours"], 48)


class FakeDailyReportRepository:
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

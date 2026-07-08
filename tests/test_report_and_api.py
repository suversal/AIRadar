import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.api.public import (
    build_daily_payload,
    build_daily_payload_from_repository,
    build_latest_payload,
    build_latest_payload_from_repository,
)
from app.models.domain import EventCluster, ProcessedArticle, RawArticle, ScoreDimensions, Source
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
            dimensions=ScoreDimensions(9, 8, 8, 8, 7, 6),
            base_score=8.0,
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
        self.assertEqual(latest["items"][0]["main_source"]["name"], "OpenAI Blog")
        self.assertEqual(
            latest["items"][0]["original_paragraphs"],
            ["OpenAI 发布新的 Agent 模型。", "开发者可以用它构建自动化工作流。"],
        )
        self.assertEqual(latest["items"][0]["original_images"][0]["url"], "https://openai.com/agent.png")
        self.assertEqual(latest["items"][0]["original_blocks"][1]["type"], "image")
        self.assertEqual(latest["items"][0]["source_language"], "en")
        self.assertEqual(
            latest["items"][0]["translated_paragraphs"],
            ["OpenAI 发布新的 Agent 模型。", "开发者可以用它构建自动化工作流。"],
        )
        self.assertEqual(latest["items"][0]["translated_blocks"][1]["type"], "image")
        self.assertEqual(daily["report_date"], "2026-07-01")

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

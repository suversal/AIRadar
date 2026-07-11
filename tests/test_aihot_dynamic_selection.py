import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.models.domain import PrefilterResult, ScoreDimensions, ScoringResult, Source
from app.pipeline.runner import run_pipeline
from app.services.ai_service import FakeAIProvider


class LowScoreProvider(FakeAIProvider):
    def prefilter(self, text):
        raise AssertionError("trusted curated items must bypass the relevance prefilter")

    def score_article(self, title, content):
        return ScoringResult(
            dimensions=ScoreDimensions(2, 2, 2, 2, 2, 2),
            category="industry",
            tags=["AI HOT"],
            title_zh=title,
            one_line_summary=content,
            summary_zh=content,
            reason_zh="原站每日精编",
            action_zh="阅读原文",
        )

    def embed_text(self, text, dimensions=512):
        # Each title gets its own deterministic event.
        index = int(text.split("条目 ", 1)[1].split("\n", 1)[0])
        vector = [0.0] * 20
        vector[index % 20] = 1.0
        return vector


def aihot_source():
    return Source(
        id="aihot_feed",
        name="AI HOT 每日精选",
        source_role="aggregator",
        tier="T3",
        type="rss",
        category="media",
        url="https://aihot.virxact.com/feed.xml",
        homepage="https://aihot.virxact.com",
        allowed_domains=["aihot.virxact.com"],
        language="zh",
        can_be_main_source=False,
        config={"crawl_limit": 50, "selection_policy": "trusted_curated"},
    )


class AIHotDynamicSelectionTests(unittest.TestCase):
    def test_trusted_curated_items_bypass_candidate_budget_and_score_threshold(self):
        source = aihot_source()
        items = [
            {
                "source_url": f"https://aihot.virxact.com/posts/{index}",
                "title": f"条目 {index}",
                "content": f"这是第 {index} 条 AI 精编内容，正文完整。",
                "author": "AI HOT",
                "published_at": datetime(2026, 7, 1, 4, tzinfo=timezone.utc),
                "language": "zh",
                "raw_score": {},
                "metadata": {"feed_position": index + 1},
            }
            for index in range(13)
        ]

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={source.id: items},
            ai_provider=LowScoreProvider(),
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
            candidate_limit=1,
        )

        self.assertEqual(len(result.processed_articles), 13)
        self.assertTrue(all(item.selected for item in result.processed_articles))
        self.assertTrue(all(item.selection_origin == "curated_source" for item in result.processed_articles))
        self.assertEqual(result.daily_report.article_count, 13)
        self.assertNotIn("candidate_limit", result.skipped_reasons)

    def test_trusted_member_selects_event_but_official_source_remains_main(self):
        curated = aihot_source()
        official = Source(
            id="official",
            name="Official",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://official.example/feed.xml",
            homepage="https://official.example",
            allowed_domains=["official.example"],
        )

        class SameVectorProvider(LowScoreProvider):
            def prefilter(self, text):
                return PrefilterResult(True, 1.0, "test")

            def embed_text(self, text, dimensions=512):
                return [1.0, 0.0]

        common = {
            "content": "同一个 AI 产品发布事件的完整正文。",
            "author": None,
            "published_at": datetime(2026, 7, 1, 4, tzinfo=timezone.utc),
            "language": "zh",
            "raw_score": {},
            "metadata": {},
        }
        result = run_pipeline(
            sources=[curated, official],
            raw_items_by_source={
                curated.id: [
                    {
                        **common,
                        "source_url": "https://aihot.virxact.com/posts/merged",
                        "title": "条目 3",
                    }
                ],
                official.id: [
                    {
                        **common,
                        "source_url": "https://official.example/release",
                        "title": "条目 4",
                    }
                ],
            },
            ai_provider=SameVectorProvider(),
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
        )

        self.assertEqual(result.daily_report.article_count, 1)
        self.assertEqual(result.daily_report.json_data["items"][0]["main_source"]["name"], "Official")

    def test_daily_report_uses_shanghai_calendar_date(self):
        source = aihot_source()
        items = [
            {
                "source_url": "https://aihot.virxact.com/posts/yesterday",
                "title": "条目 1",
                "content": "AI 精编正文一",
                "author": "AI HOT",
                "published_at": datetime(2026, 6, 30, 15, 59, tzinfo=timezone.utc),
                "language": "zh",
                "raw_score": {},
                "metadata": {},
            },
            {
                "source_url": "https://aihot.virxact.com/posts/today",
                "title": "条目 2",
                "content": "AI 精编正文二",
                "author": "AI HOT",
                "published_at": datetime(2026, 6, 30, 16, 0, tzinfo=timezone.utc),
                "language": "zh",
                "raw_score": {},
                "metadata": {},
            },
        ]

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={source.id: items},
            ai_provider=LowScoreProvider(),
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
        )

        self.assertEqual(result.daily_report.article_count, 1)
        self.assertEqual(result.daily_report.json_data["items"][0]["title"], "条目 2")


if __name__ == "__main__":
    unittest.main()

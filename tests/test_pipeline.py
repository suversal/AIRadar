import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.models.domain import PrefilterResult, ScoreDimensions, ScoringResult, Source
from app.pipeline.runner import run_pipeline
from app.services.ai_service import FakeAIProvider


class PipelineTests(unittest.TestCase):
    def test_pipeline_skips_over_limit_and_generates_daily_report(self):
        source = Source(
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
        raw_items = [
            {
                "source_url": "https://openai.com/a",
                "title": "OpenAI releases agent model",
                "content": "OpenAI releases a new AI agent model for developers.",
                "author": "OpenAI",
                "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            },
            {
                "source_url": "https://openai.com/b",
                "title": "Office lunch menu",
                "content": "Cafeteria update.",
                "author": "OpenAI",
                "published_at": datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            },
            {
                "source_url": "https://openai.com/c",
                "title": "Anthropic Claude Code improves agent workflows",
                "content": "AI coding assistant update for agent workflows.",
                "author": "Anthropic",
                "published_at": datetime(2026, 7, 1, 10, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            },
        ]

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={"openai_blog": raw_items},
            ai_provider=FakeAIProvider(),
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
            candidate_limit=2,
            top_n=12,
        )

        self.assertEqual(len(result.raw_articles), 3)
        self.assertEqual(len(result.processed_articles), 1)
        self.assertEqual(len(result.event_clusters), 1)
        self.assertIn("Suversal AI Radar 日报", result.daily_report.markdown)
        self.assertEqual(result.skipped_reasons["candidate_limit"], 1)
        self.assertEqual(result.skipped_reasons["not_ai_related"], 1)

    def test_pipeline_fills_report_from_below_threshold_candidates(self):
        source = Source(
            id="hn",
            name="Hacker News",
            source_role="signal",
            tier="T2",
            type="api",
            category="community",
            url="https://hn.algolia.com/api/v1/search",
            homepage="https://news.ycombinator.com",
            allowed_domains=["news.ycombinator.com"],
        )
        raw_items = [
            {
                "source_url": f"https://example.com/{index}",
                "title": f"AI agent workflow update {index}",
                "content": "AI agent workflow update for builders.",
                "author": None,
                "published_at": datetime(2026, 7, 1, 8 + index, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            }
            for index in range(3)
        ]

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={"hn": raw_items},
            ai_provider=LowScoreAIProvider(),
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
            candidate_limit=10,
            top_n=2,
        )

        self.assertEqual(result.skipped_reasons["below_threshold"], 3)
        self.assertEqual(len([item for item in result.processed_articles if item.selected]), 0)
        self.assertEqual(result.daily_report.article_count, 2)
        self.assertEqual(len(result.daily_report.json_data["items"]), 2)


class LowScoreAIProvider(FakeAIProvider):
    def prefilter(self, text: str) -> PrefilterResult:
        return PrefilterResult(is_ai_related=True, confidence=0.9, reason="fixture")

    def score_article(self, title: str, content: str) -> ScoringResult:
        return ScoringResult(
            dimensions=ScoreDimensions(
                ai_relevance=6,
                novelty=5,
                impact=5,
                information_density=5,
                actionability=4,
                creator_value=4,
            ),
            category="industry",
            tags=["AI"],
            title_zh=title,
            one_line_summary=f"{title}。",
            summary_zh=f"{title}。{content}",
            reason_zh="低分候选仍可用于补足完整成果。",
            action_zh="阅读原文后再判断。",
        )


if __name__ == "__main__":
    unittest.main()

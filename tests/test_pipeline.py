import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.models.domain import Source
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


if __name__ == "__main__":
    unittest.main()


import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.models.domain import RawArticle, ScoreDimensions, Source
from app.services.scoring_service import (
    category_threshold,
    compute_base_score,
    compute_final_score,
    select_processed_article,
)


class ScoringTests(unittest.TestCase):
    def test_base_score_uses_prd_dimension_weights(self):
        score = compute_base_score(
            ScoreDimensions(
                ai_relevance=10,
                novelty=8,
                impact=6,
                information_density=4,
                actionability=2,
                creator_value=1,
            )
        )

        self.assertAlmostEqual(score, 6.2)

    def test_final_score_applies_tier_and_freshness(self):
        now = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)
        score = compute_final_score(
            base_score=7.0,
            source_tier="T1",
            category="model_release",
            published_at=now - timedelta(hours=2),
            now=now,
            source_count=3,
            is_duplicate=False,
        )

        self.assertGreater(score, 90)

    def test_select_processed_article_uses_category_threshold(self):
        self.assertEqual(category_threshold("research"), 75)

        article = RawArticle(
            id="a1",
            source_id="openai_blog",
            source_name="OpenAI Blog",
            source_role="authority",
            source_tier="T1",
            source_url="https://openai.com/a",
            title="Model release",
            content="AI model release",
            author=None,
            published_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
            language="en",
            raw_score={},
            metadata={},
            title_hash="t",
            url_hash="u",
        )
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

        processed = select_processed_article(
            article=article,
            source=source,
            dimensions=ScoreDimensions(
                ai_relevance=9,
                novelty=8,
                impact=8,
                information_density=8,
                actionability=7,
                creator_value=6,
            ),
            category="model_release",
            tags=["model"],
            generated_fields={
                "title_zh": "模型发布",
                "one_line_summary": "OpenAI 发布模型。",
                "summary_zh": "OpenAI 发布模型。",
                "reason_zh": "值得关注。",
                "action_zh": "阅读原文。",
            },
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            source_count=1,
        )

        self.assertTrue(processed.selected)
        self.assertGreaterEqual(processed.final_score, category_threshold("model_release"))


if __name__ == "__main__":
    unittest.main()


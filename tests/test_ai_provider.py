import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.services.ai_service import FakeAIProvider, parse_prefilter_payload, parse_scoring_payload


class AIProviderTests(unittest.TestCase):
    def test_parse_prefilter_payload_rejects_missing_required_fields(self):
        with self.assertRaises(ValueError):
            parse_prefilter_payload({"is_ai_related": True})

    def test_parse_scoring_payload_clamps_dimension_scores(self):
        parsed = parse_scoring_payload(
            {
                "dimensions": {
                    "ai_relevance": 12,
                    "novelty": -1,
                    "impact": 7,
                    "information_density": 8,
                    "actionability": 6,
                    "creator_value": 5,
                },
                "category": "model_release",
                "tags": ["Agent", "OpenAI"],
                "title_zh": "模型发布",
                "one_line_summary": "一句话",
                "summary_zh": "摘要",
                "reason_zh": "理由",
                "action_zh": "阅读原文",
            }
        )

        self.assertEqual(parsed.dimensions.ai_relevance, 10)
        self.assertEqual(parsed.dimensions.novelty, 0)

    def test_fake_provider_marks_ai_content_related_and_embeds_deterministically(self):
        provider = FakeAIProvider()

        self.assertTrue(provider.prefilter("OpenAI releases a new agent model").is_ai_related)
        self.assertEqual(
            provider.embed_text("same text"),
            provider.embed_text("same text"),
        )


if __name__ == "__main__":
    unittest.main()


import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.services.taxonomy import (
    DISPLAY_CATEGORIES,
    category_label,
    display_category,
    scoring_categories_for,
)


class TaxonomyTests(unittest.TestCase):
    def test_display_categories_match_reference_site_filters(self):
        self.assertEqual(
            [key for key, _ in DISPLAY_CATEGORIES],
            ["model", "product", "industry", "research", "tutorial"],
        )
        self.assertEqual(dict(DISPLAY_CATEGORIES)["model"], "模型")
        self.assertEqual(dict(DISPLAY_CATEGORIES)["tutorial"], "技巧")

    def test_every_scoring_category_maps_to_a_display_category(self):
        expectations = {
            "model_release": "model",
            "product_release": "product",
            "open_source": "product",
            "industry": "industry",
            "funding": "industry",
            "research": "research",
            "opinion": "tutorial",
            "tutorial": "tutorial",
        }
        for scoring, display in expectations.items():
            self.assertEqual(display_category(scoring), display)

    def test_unknown_scoring_categories_fall_back_by_keyword_then_industry(self):
        # real DeepSeek output has produced e.g. "research_insight"
        self.assertEqual(display_category("research_insight"), "research")
        self.assertEqual(display_category("model_update"), "model")
        self.assertEqual(display_category("mystery"), "industry")
        self.assertEqual(display_category(""), "industry")
        self.assertEqual(display_category(None), "industry")
        # observed legacy values from pre-constraint prompt runs
        self.assertEqual(display_category("tool_release"), "product")
        self.assertEqual(display_category("framework_update"), "product")
        self.assertEqual(display_category("application_launch"), "product")
        self.assertEqual(display_category("expert_opinion"), "tutorial")
        self.assertEqual(display_category("safety_research"), "research")
        self.assertEqual(display_category("policy_regulation"), "industry")

    def test_scoring_categories_for_expands_display_category(self):
        self.assertEqual(
            scoring_categories_for("product"), ["product_release", "open_source"]
        )
        self.assertEqual(scoring_categories_for("model"), ["model_release"])
        # unknown display keys expand to themselves so raw scoring values keep working
        self.assertEqual(scoring_categories_for("research_insight"), ["research_insight"])

    def test_category_label_returns_chinese_names(self):
        self.assertEqual(category_label("model"), "模型")
        self.assertEqual(category_label("model_release"), "模型")
        self.assertEqual(category_label("unheard_of"), "行业")


if __name__ == "__main__":
    unittest.main()

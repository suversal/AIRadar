import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.models.domain import ContentValueDimensions, RawArticle, Source
from app.services.scoring_service import (
    VALUE_SCORE_THRESHOLD,
    compute_final_score,
    compute_value_score,
    select_processed_article,
)


def _article(**overrides) -> RawArticle:
    defaults = dict(
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
    defaults.update(overrides)
    return RawArticle(**defaults)


def _source(tier: str = "T1") -> Source:
    return Source(
        id="openai_blog",
        name="OpenAI Blog",
        source_role="authority",
        tier=tier,
        type="rss",
        category="official",
        url="https://openai.com/rss.xml",
        homepage="https://openai.com",
        allowed_domains=["openai.com"],
        can_be_main_source=True,
    )


_GENERATED_FIELDS = {
    "title_zh": "模型发布",
    "one_line_summary": "OpenAI 发布模型。",
    "summary_zh": "OpenAI 发布模型。",
    "reason_zh": "值得关注。",
    "action_zh": "阅读原文。",
}


class ScoringTests(unittest.TestCase):
    def test_compute_value_score_uses_weighted_dimensions(self):
        # impact*0.4 + novelty*0.3 + substance*0.3, 0-10 -> 0-100
        score = compute_value_score(ContentValueDimensions(impact=9, novelty=8, substance=7))
        self.assertAlmostEqual(score, (9 * 0.4 + 8 * 0.3 + 7 * 0.3) * 10)

    def test_compute_final_score_applies_tier_coefficient_as_a_boost_only(self):
        dims = ContentValueDimensions(impact=7, novelty=6, substance=7)
        raw = compute_value_score(dims)  # 67.0

        # T3 是基线，不打折——同样的内容从T3信源报道出来，分数不应该被扣分
        self.assertAlmostEqual(compute_final_score(dims, "T3"), raw)
        # T2/T1 只加成，不惩罚
        self.assertAlmostEqual(compute_final_score(dims, "T2"), round(raw * 1.1, 2))
        self.assertAlmostEqual(compute_final_score(dims, "T1"), round(raw * 1.2, 2))

    def test_compute_final_score_clamps_at_100(self):
        dims = ContentValueDimensions(impact=10, novelty=10, substance=10)
        self.assertEqual(compute_value_score(dims), 100.0)
        # 100 * 1.2 = 120，必须封顶在100，不能真的超过100分
        self.assertEqual(compute_final_score(dims, "T1"), 100.0)

    def test_compute_final_score_defaults_unknown_tier_to_no_boost(self):
        dims = ContentValueDimensions(impact=7, novelty=6, substance=7)
        raw = compute_value_score(dims)
        self.assertAlmostEqual(compute_final_score(dims, "unconfigured"), raw)

    def test_select_processed_article_selects_high_value_primary_content(self):
        processed = select_processed_article(
            article=_article(),
            source=_source("T1"),
            ai_focus="primary",
            dimensions=ContentValueDimensions(impact=9, novelty=8, substance=8),
            category="model_release",
            tags=["model"],
            generated_fields=_GENERATED_FIELDS,
        )

        self.assertTrue(processed.selected)
        self.assertIsNone(processed.rejection_reason)
        self.assertGreaterEqual(processed.final_score, VALUE_SCORE_THRESHOLD)
        self.assertEqual(processed.focus_category, "model")

    def test_select_processed_article_maps_tutorial_category_to_tutorial_focus(self):
        processed = select_processed_article(
            article=_article(
                id="a2",
                source_url="https://openai.com/b",
                title="How-to guide",
                content="Step by step tutorial",
                title_hash="t2",
                url_hash="u2",
            ),
            source=_source("T1"),
            ai_focus="contributing",
            dimensions=ContentValueDimensions(impact=6, novelty=6, substance=7),
            category="tutorial",
            tags=["教程"],
            generated_fields={
                "title_zh": "最佳实践教程",
                "one_line_summary": "手把手教程。",
                "summary_zh": "手把手教程。",
                "reason_zh": "值得关注。",
                "action_zh": "阅读原文。",
            },
        )

        self.assertEqual(processed.focus_category, "tutorial")

    def test_select_processed_article_rejects_tangential_regardless_of_value_score(self):
        # 回归用例:鸿蒙智行尊界S800 OTA稿真实案例的简化重建 - 内容写得很
        # 具体(高impact/novelty/substance)，但AI/智驾只是车辆功能列表里的
        # 一项，不是文章主体，ai_focus分类层必须挡住它，不能让高分把它捞回来
        processed = select_processed_article(
            article=_article(
                title="鸿蒙智行 OTA 尊界 S800 全系暑期版本推送",
                content="WEWA 2.0 领航升级、新增城区漫游巡航、车外喊话、无麦K歌2.0",
            ),
            source=_source("T1"),
            ai_focus="tangential",
            dimensions=ContentValueDimensions(impact=9, novelty=8, substance=9),
            category="product_release",
            tags=["智驾", "OTA"],
            generated_fields=_GENERATED_FIELDS,
        )

        self.assertFalse(processed.selected)
        self.assertEqual(processed.rejection_reason, "ai_focus:tangential")
        # 就算按加权公式算,这个分数本身是达标的 - 证明是分类层单独挡下来的,
        # 不是价值分不够
        self.assertGreaterEqual(processed.final_score, VALUE_SCORE_THRESHOLD)

    def test_select_processed_article_rejects_low_value_content(self):
        processed = select_processed_article(
            article=_article(),
            source=_source("T1"),
            ai_focus="primary",
            dimensions=ContentValueDimensions(impact=2, novelty=2, substance=2),
            category="model_release",
            tags=["model"],
            generated_fields=_GENERATED_FIELDS,
        )

        self.assertFalse(processed.selected)
        self.assertTrue(processed.rejection_reason.startswith("final_score:"))

    def test_select_processed_article_never_penalizes_lower_tier_content(self):
        # 2026-07-28讨论中的真实案例:一篇T3信源报道的Kimi K3开源新闻,内容
        # 分本身是67分(中等偏上),不应该因为信源是T3就被打折扣到67分以下
        dims = ContentValueDimensions(impact=7, novelty=6, substance=7)
        processed = select_processed_article(
            article=_article(),
            source=_source("T3"),
            ai_focus="primary",
            dimensions=dims,
            category="open_source",
            tags=["开源"],
            generated_fields=_GENERATED_FIELDS,
        )

        self.assertEqual(processed.final_score, compute_value_score(dims))
        self.assertTrue(processed.selected)


if __name__ == "__main__":
    unittest.main()

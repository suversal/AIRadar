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


def _source(tier: str = "T1", *, source_id: str = "openai_blog") -> Source:
    return Source(
        id=source_id,
        name="arXiv AI" if source_id == "arxiv_ai" else "OpenAI Blog",
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
            article=_article(title="AI product overview"),
            source=_source("T1"),
            ai_focus="primary",
            dimensions=ContentValueDimensions(impact=2, novelty=2, substance=2),
            category="product_release",
            tags=["product"],
            generated_fields={
                **_GENERATED_FIELDS,
                "title_zh": "AI 产品概览",
            },
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

    def test_ordinary_content_uses_65_as_the_selection_boundary(self):
        below = select_processed_article(
            article=_article(title="AI product update"),
            source=_source("T3"),
            ai_focus="primary",
            dimensions=ContentValueDimensions(impact=6.4, novelty=6.4, substance=6.4),
            category="product_release",
            tags=["product"],
            generated_fields={**_GENERATED_FIELDS, "title_zh": "AI 产品更新"},
        )
        at_boundary = select_processed_article(
            article=_article(id="a65", title="AI product improvement"),
            source=_source("T3"),
            ai_focus="primary",
            dimensions=ContentValueDimensions(impact=6.5, novelty=6.5, substance=6.5),
            category="product_release",
            tags=["product"],
            generated_fields={**_GENERATED_FIELDS, "title_zh": "AI 产品改进"},
        )

        self.assertEqual(below.final_score, 64.0)
        self.assertFalse(below.selected)
        self.assertEqual(at_boundary.final_score, VALUE_SCORE_THRESHOLD)
        self.assertTrue(at_boundary.selected)

    def test_arxiv_requires_breakthrough_dimensions_instead_of_tier_boost(self):
        processed = select_processed_article(
            article=_article(source_id="arxiv_ai", title="A new transformer method"),
            source=_source("T2", source_id="arxiv_ai"),
            ai_focus="primary",
            dimensions=ContentValueDimensions(impact=6, novelty=7, substance=8),
            category="research",
            tags=["paper"],
            generated_fields={**_GENERATED_FIELDS, "title_zh": "一种新的 Transformer 方法"},
        )

        # 旧逻辑下 final_score=75.9 会入选；现在 arXiv 要求三维同时过线。
        self.assertEqual(processed.final_score, 75.9)
        self.assertFalse(processed.selected)
        self.assertEqual(processed.selection_origin, "policy")
        self.assertEqual(processed.rejection_reason, "source_gate:arxiv_not_breakthrough")

    def test_arxiv_breakthrough_is_selected(self):
        processed = select_processed_article(
            article=_article(source_id="arxiv_ai", title="A breakthrough reasoning method"),
            source=_source("T2", source_id="arxiv_ai"),
            ai_focus="primary",
            dimensions=ContentValueDimensions(impact=7, novelty=8, substance=9),
            category="research",
            tags=["paper"],
            generated_fields={**_GENERATED_FIELDS, "title_zh": "突破性推理方法"},
        )

        self.assertTrue(processed.selected)
        self.assertEqual(processed.selection_origin, "policy")
        self.assertEqual(processed.selection_reason, "source_gate:arxiv_breakthrough")

    def test_confirmed_model_release_is_rescued_below_score_threshold(self):
        processed = select_processed_article(
            article=_article(title="OpenAI releases GPT-Next"),
            source=_source("T3"),
            ai_focus="primary",
            dimensions=ContentValueDimensions(impact=5, novelty=5, substance=5),
            category="model_release",
            tags=["model"],
            generated_fields={**_GENERATED_FIELDS, "title_zh": "OpenAI 正式发布 GPT-Next"},
        )

        self.assertLess(processed.final_score, VALUE_SCORE_THRESHOLD)
        self.assertTrue(processed.selected)
        self.assertEqual(processed.selection_origin, "policy")
        self.assertEqual(processed.selection_reason, "priority:confirmed_model_release")

    def test_unconfirmed_model_release_is_not_rescued(self):
        processed = select_processed_article(
            article=_article(title="OpenAI reportedly plans to release GPT-Next"),
            source=_source("T3"),
            ai_focus="primary",
            dimensions=ContentValueDimensions(impact=5, novelty=5, substance=5),
            category="model_release",
            tags=["model"],
            generated_fields={**_GENERATED_FIELDS, "title_zh": "消息称 OpenAI 将于年内发布 GPT-Next"},
        )

        self.assertFalse(processed.selected)
        self.assertTrue(processed.rejection_reason.startswith("final_score:"))

    def test_future_open_weights_announcement_is_not_rescued(self):
        processed = select_processed_article(
            article=_article(title="Ox Alpha identity confirmed"),
            source=_source("T3"),
            ai_focus="primary",
            dimensions=ContentValueDimensions(impact=5, novelty=5, substance=5),
            category="model_release",
            tags=["model"],
            generated_fields={
                **_GENERATED_FIELDS,
                "title_zh": "智谱确认 Ox Alpha 为新一代模型，今晚将开源权重",
            },
        )

        self.assertFalse(processed.selected)

    def test_model_roadmap_and_leak_are_not_rescued(self):
        cases = [
            (
                "Next-generation model roadmap",
                "智谱披露下一代大模型规划：目标发布首日支持满规模调用",
            ),
            (
                "GPT Astra Leaks: Next Week",
                "OpenAI 内部测试 GPT Astra，或于下周发布",
            ),
            (
                "GPT Astra Leaks",
                "OpenAI 内部测试 GPT Astra，或下周发布",
            ),
            (
                "GPT-6 gray test demo",
                "GPT-6 灰测 Demo 刷屏，周四或正式发布",
            ),
        ]
        for index, (title, title_zh) in enumerate(cases):
            with self.subTest(title=title):
                processed = select_processed_article(
                    article=_article(id=f"future-{index}", title=title),
                    source=_source("T3"),
                    ai_focus="primary",
                    dimensions=ContentValueDimensions(impact=5, novelty=5, substance=5),
                    category="model_release",
                    tags=["model"],
                    generated_fields={**_GENERATED_FIELDS, "title_zh": title_zh},
                )
                self.assertFalse(processed.selected)

    def test_confirmed_release_is_not_blocked_by_a_separate_future_clause(self):
        processed = select_processed_article(
            article=_article(title="OpenAI released GPT-Next, API access is coming soon"),
            source=_source("T3"),
            ai_focus="primary",
            dimensions=ContentValueDimensions(impact=5, novelty=5, substance=5),
            category="model_release",
            tags=["model"],
            generated_fields={
                **_GENERATED_FIELDS,
                "title_zh": "OpenAI 正式发布 GPT-Next，API 即将开放",
            },
        )

        self.assertTrue(processed.selected)
        self.assertEqual(processed.selection_reason, "priority:confirmed_model_release")

    def test_misclassified_chip_release_is_not_rescued_as_an_ai_model(self):
        processed = select_processed_article(
            article=_article(title="Xiaomi Xuanjie O3 chip easter egg revealed"),
            source=_source("T3"),
            ai_focus="primary",
            dimensions=ContentValueDimensions(impact=5, novelty=5, substance=5),
            category="model_release",
            tags=["chip", "NPU"],
            generated_fields={
                **_GENERATED_FIELDS,
                "title_zh": "小米发布玄戒 O3 旗舰 SoC，内置 200TOPS NPU 算力",
            },
        )

        self.assertFalse(processed.selected)

    def test_usage_limit_update_is_rescued_below_score_threshold(self):
        processed = select_processed_article(
            article=_article(title="OpenAI resets Codex usage limits"),
            source=_source("T3"),
            ai_focus="primary",
            dimensions=ContentValueDimensions(impact=3, novelty=3, substance=5),
            category="product_release",
            tags=["Codex", "quota"],
            generated_fields={**_GENERATED_FIELDS, "title_zh": "OpenAI 重置 Codex 使用额度"},
        )

        self.assertLess(processed.final_score, VALUE_SCORE_THRESHOLD)
        self.assertTrue(processed.selected)
        self.assertEqual(processed.selection_origin, "policy")
        self.assertEqual(processed.selection_reason, "priority:usage_limit_update")

    def test_generic_usage_limit_explainer_is_not_rescued(self):
        processed = select_processed_article(
            article=_article(title="How Codex usage limits work"),
            source=_source("T3"),
            ai_focus="primary",
            dimensions=ContentValueDimensions(impact=3, novelty=3, substance=5),
            category="tutorial",
            tags=["Codex", "quota"],
            generated_fields={**_GENERATED_FIELDS, "title_zh": "Codex 使用额度说明"},
        )

        self.assertFalse(processed.selected)
        self.assertTrue(processed.rejection_reason.startswith("final_score:"))


if __name__ == "__main__":
    unittest.main()

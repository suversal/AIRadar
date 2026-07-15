import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

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


class HighScoreProvider(LowScoreProvider):
    def score_article(self, title, content):
        return ScoringResult(
            dimensions=ScoreDimensions(9, 9, 9, 9, 9, 9),
            category="industry",
            tags=["AI HOT"],
            title_zh=title,
            one_line_summary=content,
            summary_zh=content,
            reason_zh="原站每日精编",
            action_zh="阅读原文",
        )


class TelegramProvider(FakeAIProvider):
    def prefilter(self, text):
        raise AssertionError("trusted Telegram items must bypass the relevance prefilter")

    def score_article(self, title, content):
        return ScoringResult(
            dimensions=ScoreDimensions(2, 2, 2, 2, 2, 2),
            category="industry",
            tags=["Telegram"],
            title_zh="AI 改写标题（不应展示）",
            one_line_summary="AI 一句话摘要",
            summary_zh="AI 根据结构化正文生成的摘要",
            reason_zh="频道直接精选",
            action_zh="查看上下文",
        )

    def embed_text(self, text, dimensions=512):
        return [1.0, 0.0, 0.0]


def telegram_source():
    return Source(
        id="telegram_zaihuapd",
        name="在花频道",
        source_role="aggregator",
        tier="T3",
        type="telegram_rss",
        category="community",
        url="https://rsshub.app/telegram/channel/zaihuapd",
        homepage="https://t.me/zaihuapd",
        allowed_domains=["t.me", "telegram.me"],
        language="zh",
        can_be_main_source=False,
        config={"selection_policy": "trusted_curated", "force_selection": "always"},
    )


def aihot_all_source():
    return Source(
        id="aihot_all",
        name="AI HOT 全部AI动态",
        source_role="aggregator",
        tier="T3",
        type="rss",
        category="media",
        url="https://aihot.virxact.com/feed/all.xml",
        homepage="https://aihot.virxact.com/all",
        allowed_domains=["aihot.virxact.com"],
        language="zh",
        can_be_main_source=False,
        config={"selection_policy": "trusted_curated", "force_selection": "never"},
    )


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
        config={
            "crawl_limit": 50,
            "selection_policy": "trusted_curated",
            "force_selection": "always",
        },
    )


class AIHotDynamicSelectionTests(unittest.TestCase):
    def test_telegram_bypasses_prefilter_forces_selection_and_preserves_rss_title(self):
        source = telegram_source()
        rss_title = "↩️ 🖼 RSS 原始标题"
        items = [
            {
                "source_url": "https://t.me/zaihuapd/42572",
                "title": rss_title,
                "content": "[回复上文] 旧消息。 当前正文。 [更新] 后续消息。",
                "author": "在花频道",
                "published_at": datetime(2026, 7, 15, 4, tzinfo=timezone.utc),
                "language": "zh",
                "raw_score": {},
                "metadata": {
                    "source_type": "telegram_rss",
                    "content_origin": "telegram_rss_description",
                    "rss_title": rss_title,
                    "original_blocks": [{"type": "paragraph", "text": "当前正文。"}],
                    "original_paragraphs": ["当前正文。"],
                    "original_text": "当前正文。",
                },
            }
        ]

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={source.id: items},
            ai_provider=TelegramProvider(),
            now=datetime(2026, 7, 15, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 15),
        )

        processed = result.processed_articles[0]
        self.assertTrue(processed.selected)
        self.assertEqual(processed.selection_origin, "curated_source")
        self.assertEqual(processed.title_zh, rss_title)
        self.assertEqual(processed.summary_zh, "AI 根据结构化正文生成的摘要")

    def test_telegram_ai_failure_uses_generic_fallback_not_aihot_copy(self):
        class FailingTelegramProvider(TelegramProvider):
            def score_article(self, title, content):
                raise RuntimeError("model unavailable")

        source = telegram_source()
        items = [
            {
                "source_url": "https://t.me/zaihuapd/42573",
                "title": "Telegram 标题",
                "content": "这是一段足够完整的正文内容。",
                "author": "在花频道",
                "published_at": datetime(2026, 7, 15, 4, tzinfo=timezone.utc),
                "language": "zh",
                "raw_score": {},
                "metadata": {
                    "source_type": "telegram_rss",
                    "rss_title": "Telegram 标题",
                },
            }
        ]

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={source.id: items},
            ai_provider=FailingTelegramProvider(),
            now=datetime(2026, 7, 15, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 15),
        )

        processed = result.processed_articles[0]
        self.assertIn("Telegram", processed.tags)
        self.assertNotIn("AI HOT", processed.tags)
        self.assertIn("可信精选信源", processed.reason_zh)
        self.assertNotIn("AI HOT", processed.reason_zh)

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
        )

        self.assertEqual(len(result.processed_articles), 13)
        self.assertTrue(all(item.selected for item in result.processed_articles))
        self.assertTrue(all(item.selection_origin == "curated_source" for item in result.processed_articles))
        self.assertEqual(result.daily_report.article_count, 13)
        self.assertNotIn("candidate_limit", result.skipped_reasons)

    def test_aihot_summary_zh_metadata_overrides_ai_generated_summary(self):
        # AI HOT's own RSS description (captured at crawl time into
        # metadata["aihot_summary_zh"]) must win over whatever summary_zh
        # our own AI scoring call would have produced
        source = aihot_source()
        items = [
            {
                "source_url": "https://aihot.virxact.com/posts/0",
                "title": "条目 0",
                "content": "这是第 0 条 AI 精编内容，正文完整。",
                "author": "AI HOT",
                "published_at": datetime(2026, 7, 1, 4, tzinfo=timezone.utc),
                "language": "zh",
                "raw_score": {},
                "metadata": {
                    "feed_position": 1,
                    "aihot_summary_zh": "AI HOT 自己写的摘要，应该原样保留。",
                },
            }
        ]

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={source.id: items},
            ai_provider=LowScoreProvider(),
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
        )

        self.assertEqual(len(result.processed_articles), 1)
        self.assertEqual(
            result.processed_articles[0].summary_zh,
            "AI HOT 自己写的摘要，应该原样保留。",
        )

    def test_aihot_permalink_routes_body_fetch_through_aihot_content_not_page_content(self):
        # an article carrying metadata["aihot_permalink"] must fetch its
        # bilingual content from AI HOT's own item page (fetch_aihot_item_content)
        # instead of the generic third-party-original fetch (prefer_full_page_content)
        source = aihot_source()
        items = [
            {
                "source_url": "https://the-decoder.com/some-article",
                "title": "条目 0",
                "content": "薄摘要占位内容",
                "author": "AI HOT",
                "published_at": datetime(2026, 7, 1, 4, tzinfo=timezone.utc),
                "language": "zh",
                "raw_score": {},
                "metadata": {
                    "feed_position": 1,
                    "body_fetch": "deferred",
                    "aihot_permalink": "https://aihot.virxact.com/items/cmrj6actv0651bilkm5pfz6ub",
                },
            }
        ]
        aihot_payload = {
            "content": "德国研究联盟发布了开源大语言模型 Soofi S。",
            "metadata": {
                "original_paragraphs": ["A German research consortium released Soofi S."],
                "original_blocks": [
                    {"type": "paragraph", "text": "A German research consortium released Soofi S."}
                ],
                "original_text": "A German research consortium released Soofi S.",
                "original_images": [],
                "translated_paragraphs": ["德国研究联盟发布了开源大语言模型 Soofi S。"],
                "translated_blocks": [
                    {"type": "paragraph", "text": "德国研究联盟发布了开源大语言模型 Soofi S。"}
                ],
                "translation_source_language": "en",
                "translation_target_language": "zh",
                "translation_status": "completed",
                "translation_source_hash": "abc123",
            },
        }

        with patch(
            "app.crawlers.aihot_content.fetch_aihot_item_content",
            return_value=aihot_payload,
        ) as mock_aihot_fetch, patch(
            "app.crawlers.page_content.prefer_full_page_content"
        ) as mock_generic_fetch:
            result = run_pipeline(
                sources=[source],
                raw_items_by_source={source.id: items},
                ai_provider=LowScoreProvider(),
                now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
                report_date=date(2026, 7, 1),
            )

        mock_aihot_fetch.assert_called_once_with(
            "https://aihot.virxact.com/items/cmrj6actv0651bilkm5pfz6ub"
        )
        mock_generic_fetch.assert_not_called()

        article = result.raw_articles[0]
        self.assertEqual(article.language, "zh")  # our own translation pipeline stays skipped
        self.assertEqual(
            article.metadata["translated_paragraphs"],
            ["德国研究联盟发布了开源大语言模型 Soofi S。"],
        )
        self.assertEqual(
            article.metadata["original_paragraphs"],
            ["A German research consortium released Soofi S."],
        )

    def test_aihot_payload_language_field_updates_article_and_triggers_generic_translation(self):
        # AI HOT sources are hardcoded language="zh" at ingestion. When their
        # own bundled translation is missing (only the English side
        # extracted), fetch_aihot_item_content now reports the actually
        # detected language via payload["language"] - the pipeline must
        # write that back onto article.language so the generic translation
        # fallback (gated on article.language.startswith("en")) actually
        # fires and fills in translated_paragraphs, instead of the
        # 原文/译文 toggle staying permanently absent for this article.
        source = aihot_source()
        items = [
            {
                "source_url": "https://the-decoder.com/some-article",
                "title": "条目 0",
                "content": "薄摘要占位内容",
                "author": "AI HOT",
                "published_at": datetime(2026, 7, 1, 4, tzinfo=timezone.utc),
                "language": "zh",
                "raw_score": {},
                "metadata": {
                    "feed_position": 1,
                    "body_fetch": "deferred",
                    "aihot_permalink": "https://aihot.virxact.com/items/english-only",
                },
            }
        ]
        aihot_payload = {
            "content": "A German research consortium released Soofi S.",
            "metadata": {
                "original_paragraphs": ["A German research consortium released Soofi S."],
                "original_blocks": [
                    {"type": "paragraph", "text": "A German research consortium released Soofi S."}
                ],
                "original_text": "A German research consortium released Soofi S.",
                "original_images": [],
            },
            "language": "en",
        }

        with patch(
            "app.crawlers.aihot_content.fetch_aihot_item_content",
            return_value=aihot_payload,
        ):
            result = run_pipeline(
                sources=[source],
                raw_items_by_source={source.id: items},
                ai_provider=LowScoreProvider(),
                now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
                report_date=date(2026, 7, 1),
            )

        article = result.raw_articles[0]
        self.assertEqual(article.language, "en")
        self.assertTrue(article.metadata.get("translated_paragraphs"))
        self.assertIn("译文：", article.metadata["translated_paragraphs"][0])

    def test_aihot_branch_skips_payload_for_unfetchable_read_original_domain(self):
        # when the "阅读原文" target resolves to a known unscrapable host
        # (WeChat), AI HOT's own item page can itself have rendered a
        # verification-wall artifact instead of real content - the pipeline
        # must not trust fetch_aihot_item_content's payload at all in that
        # case, and must leave the RSS-stage aihot_summary_zh/content
        # untouched rather than risk showing fabricated body text
        source = aihot_source()
        items = [
            {
                "source_url": "https://mp.weixin.qq.com/s/some-article",
                "title": "条目 0",
                "content": "薄摘要占位内容",
                "author": "AI HOT",
                "published_at": datetime(2026, 7, 1, 4, tzinfo=timezone.utc),
                "language": "zh",
                "raw_score": {},
                "metadata": {
                    "feed_position": 1,
                    "body_fetch": "deferred",
                    "aihot_permalink": "https://aihot.virxact.com/items/wechat-source",
                    "aihot_summary_zh": "薄摘要占位内容",
                },
            }
        ]
        # a payload that, if it were trusted, would look like a perfectly
        # normal successful extraction
        aihot_payload = {
            "content": "可能是验证页伪正文",
            "metadata": {
                "original_paragraphs": ["可能是验证页伪正文"],
                "original_blocks": [{"type": "paragraph", "text": "可能是验证页伪正文"}],
                "original_text": "可能是验证页伪正文",
                "original_images": [],
            },
            "language": "zh",
        }

        with patch(
            "app.crawlers.aihot_content.fetch_aihot_item_content",
            return_value=aihot_payload,
        ) as mock_aihot_fetch:
            result = run_pipeline(
                sources=[source],
                raw_items_by_source={source.id: items},
                ai_provider=LowScoreProvider(),
                now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
                report_date=date(2026, 7, 1),
            )

        mock_aihot_fetch.assert_not_called()

        article = result.raw_articles[0]
        self.assertEqual(article.metadata.get("content_origin"), "aihot_item_page_link_only")
        self.assertEqual(article.content, "薄摘要占位内容")
        self.assertEqual(article.metadata.get("aihot_summary_zh"), "薄摘要占位内容")
        self.assertNotIn("original_paragraphs", article.metadata)

    def test_force_selection_never_keeps_aihot_all_out_of_selection_even_at_high_score(self):
        # aihot_all shares aihot_feed's trusted_curated prefilter skip, but
        # must never enter 精选 regardless of how well it scores - unlike
        # aihot_feed, which force_selection:always pushes in unconditionally
        source = aihot_all_source()
        items = [
            {
                "source_url": f"https://aihot.virxact.com/all/{index}",
                "title": f"条目 {index}",
                "content": f"这是第 {index} 条 AI 动态内容，正文完整。",
                "author": "AI HOT",
                "published_at": datetime(2026, 7, 1, 4, tzinfo=timezone.utc),
                "language": "zh",
                "raw_score": {},
                "metadata": {"feed_position": index + 1},
            }
            for index in range(3)
        ]

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={source.id: items},
            ai_provider=HighScoreProvider(),
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
        )

        self.assertEqual(len(result.processed_articles), 3)
        self.assertFalse(any(item.selected for item in result.processed_articles))
        self.assertTrue(
            all(item.rejection_reason == f"force_selection:never:{source.id}" for item in result.processed_articles)
        )
        self.assertEqual(result.daily_report.article_count, 0)

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

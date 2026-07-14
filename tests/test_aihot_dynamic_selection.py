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

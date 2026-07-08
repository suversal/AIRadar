import sys
import threading
import time
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

    def test_pipeline_can_process_ai_candidates_concurrently(self):
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
                "source_url": f"https://example.com/concurrent-{index}",
                "title": f"AI agent concurrent update {index}",
                "content": "AI agent workflow update for builders.",
                "author": None,
                "published_at": datetime(2026, 7, 1, 8 + index, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            }
            for index in range(4)
        ]
        provider = SlowConcurrentAIProvider()

        result = run_pipeline(
            sources=[source],
            raw_items_by_source={"hn": raw_items},
            ai_provider=provider,
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
            candidate_limit=10,
            top_n=4,
            ai_concurrency=4,
        )

        self.assertGreater(provider.max_active, 1)
        self.assertEqual(result.daily_report.article_count, 4)

    def test_pipeline_translates_only_selected_english_report_articles(self):
        english_source = Source(
            id="hn",
            name="Hacker News",
            source_role="signal",
            tier="T2",
            type="api",
            category="community",
            url="https://hn.algolia.com/api/v1/search",
            homepage="https://news.ycombinator.com",
            allowed_domains=["news.ycombinator.com"],
            language="en",
        )
        chinese_source = Source(
            id="ithome",
            name="IT之家",
            source_role="media",
            tier="T3",
            type="rss",
            category="media",
            url="https://www.ithome.com/rss/",
            homepage="https://www.ithome.com",
            allowed_domains=["ithome.com"],
            language="zh",
        )
        raw_items = {
            "hn": [
                {
                    "source_url": "https://example.com/english-ai-agent",
                    "title": "AI agent audit finds seven bugs",
                    "content": "AI agents found security bugs.\nDevelopers verified the fixes.",
                    "author": "HN",
                    "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                    "language": "en",
                    "raw_score": {},
                    "metadata": {
                        "original_blocks": [
                            {"type": "paragraph", "text": "AI agents found security bugs."},
                            {
                                "type": "image",
                                "url": "https://example.com/audit.png",
                                "alt": "Audit diagram",
                                "caption": "",
                            },
                            {"type": "paragraph", "text": "Developers verified the fixes."},
                        ]
                    },
                },
                {
                    "source_url": "https://example.com/second-agent",
                    "title": "AI agent workflow update",
                    "content": "AI workflow update for builders.",
                    "author": "HN",
                    "published_at": datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
                    "language": "en",
                    "raw_score": {},
                    "metadata": {},
                },
            ],
            "ithome": [
                {
                    "source_url": "https://ithome.com/ai",
                    "title": "AI 公司发布新工具",
                    "content": "这是一条中文 AI 新闻。",
                    "author": "IT之家",
                    "published_at": datetime(2026, 7, 1, 10, tzinfo=timezone.utc),
                    "language": "zh",
                    "raw_score": {},
                    "metadata": {},
                }
            ],
        }
        provider = TranslatingAIProvider()

        result = run_pipeline(
            sources=[english_source, chinese_source],
            raw_items_by_source=raw_items,
            ai_provider=provider,
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
            candidate_limit=10,
            top_n=1,
        )

        item = result.daily_report.json_data["items"][0]
        self.assertEqual(provider.translation_calls, [["AI agents found security bugs.", "Developers verified the fixes."]])
        self.assertEqual(item["source_language"], "en")
        self.assertEqual(item["translated_paragraphs"], ["译文：AI agents found security bugs.", "译文：Developers verified the fixes."])
        self.assertEqual(item["translated_blocks"][1]["type"], "image")
        self.assertEqual(item["translated_blocks"][1]["url"], "https://example.com/audit.png")


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


class SlowConcurrentAIProvider(FakeAIProvider):
    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def _enter_call(self):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.03)
        with self.lock:
            self.active -= 1

    def prefilter(self, text: str) -> PrefilterResult:
        self._enter_call()
        return PrefilterResult(is_ai_related=True, confidence=0.9, reason="fixture")

    def score_article(self, title: str, content: str) -> ScoringResult:
        self._enter_call()
        return super().score_article(title, content)


class TranslatingAIProvider(FakeAIProvider):
    def __init__(self):
        self.translation_calls = []

    def prefilter(self, text: str) -> PrefilterResult:
        return PrefilterResult(is_ai_related=True, confidence=0.9, reason="fixture")

    def score_article(self, title: str, content: str) -> ScoringResult:
        score = 9 if "seven bugs" in title else 6
        return ScoringResult(
            dimensions=ScoreDimensions(
                ai_relevance=score,
                novelty=score,
                impact=score,
                information_density=score,
                actionability=score,
                creator_value=score,
            ),
            category="industry",
            tags=["AI"],
            title_zh=title,
            one_line_summary=f"{title}。",
            summary_zh=f"{title}。{content}",
            reason_zh="用于验证英文原文译文生成。",
            action_zh="对照阅读原文和译文。",
        )

    def translate_paragraphs(self, paragraphs):
        self.translation_calls.append(list(paragraphs))
        return [f"译文：{paragraph}" for paragraph in paragraphs]


if __name__ == "__main__":
    unittest.main()

import sys
import threading
import time
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

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

    def test_pipeline_isolates_single_article_ai_failures(self):
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
                "source_url": "https://openai.com/good",
                "title": "OpenAI releases agent model",
                "content": "OpenAI releases a new AI agent model for developers.",
                "author": "OpenAI",
                "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            },
            {
                "source_url": "https://openai.com/poison",
                "title": "Anthropic AI safety research update",
                "content": "AI safety research update triggers a provider glitch.",
                "author": "Anthropic",
                "published_at": datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
                "language": "en",
                "raw_score": {},
                "metadata": {},
            },
        ]

        class FlakyProvider(FakeAIProvider):
            def score_article(self, title, content):
                if "safety" in title.lower():
                    raise ValueError("Chat response was not valid JSON")
                return super().score_article(title, content)

        for concurrency in [1, 4]:
            with self.subTest(concurrency=concurrency):
                result = run_pipeline(
                    sources=[source],
                    raw_items_by_source={"openai_blog": raw_items},
                    ai_provider=FlakyProvider(),
                    now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
                    report_date=date(2026, 7, 1),
                    candidate_limit=10,
                    top_n=12,
                    ai_concurrency=concurrency,
                )

                self.assertEqual(result.skipped_reasons["ai_error"], 1)
                self.assertEqual(len(result.processed_articles), 1)
                poison = next(
                    article
                    for article in result.raw_articles
                    if article.source_url.endswith("/poison")
                )
                self.assertEqual(poison.status, "skipped")
                self.assertEqual(poison.skipped_reason, "ai_error")

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

    def test_pipeline_can_skip_prefilter_and_score_every_candidate(self):
        source = Source(
            id="mixed",
            name="Mixed Feed",
            source_role="signal",
            tier="T2",
            type="rss",
            category="community",
            url="https://example.com/feed",
            homepage="https://example.com",
            allowed_domains=["example.com"],
        )
        raw_items = [
            {
                "source_url": f"https://example.com/{index}",
                "title": f"General update {index}",
                "content": "This item has no explicit AI keyword.",
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
            raw_items_by_source={"mixed": raw_items},
            ai_provider=NonAiPrefilterProvider(),
            now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
            report_date=date(2026, 7, 1),
            candidate_limit=3,
            top_n=3,
            skip_prefilter=True,
        )

        self.assertEqual(len(result.processed_articles), 3)
        self.assertEqual(result.daily_report.article_count, 3)
        self.assertNotIn("not_ai_related", result.skipped_reasons)

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

    def test_pipeline_attaches_readme_only_for_selected_github_articles_before_translation(self):
        github_source = Source(
            id="github_trending_ai",
            name="GitHub Trending AI",
            source_role="signal",
            tier="T2",
            type="github",
            category="community",
            url="https://github.com/trending?since=daily",
            homepage="https://github.com/trending",
            allowed_domains=["github.com"],
            language="en",
        )
        hn_source = Source(
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
        raw_items = {
            "github_trending_ai": [
                {
                    "source_url": "https://github.com/MadsLorentzen/ai-job-search",
                    "title": "AI selected readme project",
                    "content": "Short trending description.",
                    "author": "MadsLorentzen",
                    "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                    "language": "en",
                    "raw_score": {},
                    "metadata": {
                        "repo": "MadsLorentzen/ai-job-search",
                        "source_type": "github_trending",
                    },
                },
                {
                    "source_url": "https://github.com/example/unselected-agent",
                    "title": "AI low priority repo project",
                    "content": "Another short description.",
                    "author": "example",
                    "published_at": datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
                    "language": "en",
                    "raw_score": {},
                    "metadata": {
                        "repo": "example/unselected-agent",
                        "source_type": "github_trending",
                    },
                },
            ],
            "hn": [
                {
                    "source_url": "https://example.com/non-github-agent",
                    "title": "AI non github selected story",
                    "content": "A non GitHub story that should not fetch README.",
                    "author": "hn",
                    "published_at": datetime(2026, 7, 1, 10, tzinfo=timezone.utc),
                    "language": "en",
                    "raw_score": {},
                    "metadata": {},
                }
            ],
        }
        provider = ReadmeAwareAIProvider()
        readme_payload = {
            "readme_status": "ok",
            "readme_url": "https://raw.githubusercontent.com/MadsLorentzen/ai-job-search/main/README.md",
            "original_content": "AI Job Search\n\nFull README details for the project.",
            "original_markdown": "# AI Job Search\n\nFull README details for the project.",
            "original_paragraphs": ["AI Job Search", "Full README details for the project."],
            "original_blocks": [
                {"type": "paragraph", "text": "AI Job Search"},
                {"type": "paragraph", "text": "Full README details for the project."},
            ],
            "original_images": [],
        }

        with patch("app.pipeline.runner.fetch_github_readme", return_value=readme_payload) as fetch_readme:
            result = run_pipeline(
                sources=[github_source, hn_source],
                raw_items_by_source=raw_items,
                ai_provider=provider,
                now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
                report_date=date(2026, 7, 1),
                candidate_limit=10,
                top_n=2,
            )

        fetch_readme.assert_called_once_with("MadsLorentzen/ai-job-search")
        github_item = next(
            item for item in result.daily_report.json_data["items"]
            if item["original_url"] == "https://github.com/MadsLorentzen/ai-job-search"
        )
        self.assertEqual(github_item["original_paragraphs"], readme_payload["original_paragraphs"])
        self.assertEqual(github_item["original_markdown"], readme_payload["original_markdown"])
        self.assertNotIn("translated_paragraphs", github_item)
        self.assertNotIn("translated_blocks", github_item)
        github_article = next(
            article for article in result.raw_articles
            if article.source_url == "https://github.com/MadsLorentzen/ai-job-search"
        )
        self.assertEqual(github_article.metadata["repo_description"], "Short trending description.")
        self.assertEqual(github_article.metadata["readme_status"], "ok")
        self.assertEqual(provider.translation_calls, [["A non GitHub story that should not fetch README."]])

    def test_pipeline_skips_translation_for_selected_chinese_readme(self):
        github_source = Source(
            id="github_trending_ai",
            name="GitHub Trending AI",
            source_role="signal",
            tier="T2",
            type="github",
            category="community",
            url="https://github.com/trending?since=daily",
            homepage="https://github.com/trending",
            allowed_domains=["github.com"],
            language="en",
        )
        raw_items = {
            "github_trending_ai": [
                {
                    "source_url": "https://github.com/TencentCloud/TencentDB-Agent-Memory",
                    "title": "AI selected readme zh project",
                    "content": "Short trending description.",
                    "author": "TencentCloud",
                    "published_at": datetime(2026, 7, 1, 8, tzinfo=timezone.utc),
                    "language": "en",
                    "raw_score": {},
                    "metadata": {
                        "repo": "TencentCloud/TencentDB-Agent-Memory",
                        "source_type": "github_trending",
                    },
                }
            ],
        }
        provider = ReadmeAwareAIProvider()
        readme_payload = {
            "readme_status": "ok",
            "readme_url": "https://raw.githubusercontent.com/TencentCloud/TencentDB-Agent-Memory/main/README_CN.md",
            "readme_name": "README_CN.md",
            "readme_language": "zh",
            "readme_selection": "preferred_zh_readme",
            "original_content": "中文说明\n\n这是中文 README。",
            "original_markdown": "# 中文说明\n\n这是中文 README。",
            "original_paragraphs": ["中文说明", "这是中文 README。"],
            "original_blocks": [
                {"type": "paragraph", "text": "中文说明"},
                {"type": "paragraph", "text": "这是中文 README。"},
            ],
            "original_images": [],
        }

        with patch("app.pipeline.runner.fetch_github_readme", return_value=readme_payload):
            result = run_pipeline(
                sources=[github_source],
                raw_items_by_source=raw_items,
                ai_provider=provider,
                now=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
                report_date=date(2026, 7, 1),
                candidate_limit=10,
                top_n=1,
            )

        github_item = result.daily_report.json_data["items"][0]
        self.assertEqual(github_item["readme_name"], "README_CN.md")
        self.assertEqual(github_item["readme_language"], "zh")
        self.assertEqual(github_item["readme_selection"], "preferred_zh_readme")
        self.assertEqual(github_item["original_markdown"], "# 中文说明\n\n这是中文 README。")
        self.assertNotIn("translated_paragraphs", github_item)
        self.assertNotIn("translated_blocks", github_item)
        self.assertEqual(provider.translation_calls, [])


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


class NonAiPrefilterProvider(FakeAIProvider):
    def prefilter(self, text: str) -> PrefilterResult:
        return PrefilterResult(is_ai_related=False, confidence=0.9, reason="fixture")


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


class ReadmeAwareAIProvider(TranslatingAIProvider):
    def score_article(self, title: str, content: str) -> ScoringResult:
        if "selected readme" in title:
            score = 9
        elif "non github selected" in title:
            score = 8
        else:
            score = 5
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
            reason_zh="用于验证 GitHub README 原文。",
            action_zh="对照阅读 README。",
        )


if __name__ == "__main__":
    unittest.main()

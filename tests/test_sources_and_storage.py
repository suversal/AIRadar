import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.data.default_sources import default_sources
from app.storage.json_store import load_sources, save_sources


class SourcesAndStorageTests(unittest.TestCase):
    def test_default_sources_cover_required_first_batch(self):
        sources = default_sources()
        source_ids = {source.id for source in sources}

        self.assertIn("openai_blog", source_ids)
        self.assertIn("hacker_news", source_ids)
        self.assertIn("arxiv_ai", source_ids)
        self.assertIn("github_trending_ai", source_ids)
        self.assertIn("reddit_localllama", source_ids)
        self.assertIn("ithome", source_ids)
        self.assertTrue(any(source.source_role == "authority" for source in sources))
        self.assertTrue(any(source.source_role == "signal" for source in sources))

        ithome = next(source for source in sources if source.id == "ithome")
        self.assertEqual(ithome.url, "https://www.ithome.com/rss/")
        self.assertEqual(ithome.language, "zh")
        self.assertTrue(ithome.config["extract_original_content"])

        aihot = next(source for source in sources if source.id == "aihot_feed")
        self.assertEqual(aihot.url, "https://aihot.virxact.com/feed.xml")
        self.assertEqual(aihot.source_role, "aggregator")
        self.assertEqual(aihot.tier, "T3")
        self.assertEqual(aihot.language, "zh")
        self.assertFalse(aihot.can_be_main_source)
        self.assertFalse(aihot.affects_heat_score)
        self.assertEqual(aihot.config["crawl_limit"], 50)
        self.assertEqual(aihot.config["selection_policy"], "trusted_curated")
        # 正文必须从"阅读原文"页面抓取（2026-07-11 决策），feed 摘要只是
        # 抓取失败时的回退——绝不能配置成只用 feed 内容
        self.assertNotIn("use_feed_content_only", aihot.config)
        self.assertTrue(aihot.config["original_url_from_description"])

        telegram_ids = {
            "telegram_zaihuapd",
            "telegram_xhqcankao",
            "telegram_dnspodt",
        }
        self.assertTrue(telegram_ids.issubset(source_ids))
        for source in (source for source in sources if source.id in telegram_ids):
            self.assertEqual(source.type, "telegram_rss")
            self.assertEqual(source.source_role, "aggregator")
            self.assertFalse(source.can_be_main_source)
            self.assertFalse(source.affects_heat_score)
            self.assertEqual(source.config["selection_policy"], "trusted_curated")
            self.assertNotIn("force_selection", source.config)
            self.assertEqual(source.config["recent_days"], 1)
            self.assertTrue(source.config["use_feed_content_only"])

    def test_default_sources_second_batch_replaces_dead_feeds(self):
        sources = default_sources()
        by_id = {source.id: source for source in sources}

        # 机器之心 RSS 已下线，返回 HTML 页面，不能再作为默认源。
        self.assertNotIn("jiqizhixin", by_id)

        anthropic = by_id["anthropic_news"]
        self.assertEqual(anthropic.type, "sitemap")
        self.assertEqual(anthropic.url, "https://www.anthropic.com/sitemap.xml")
        self.assertEqual(
            anthropic.config["path_prefix"], "https://www.anthropic.com/news/"
        )

        deepmind = by_id["deepmind_blog"]
        self.assertEqual(deepmind.url, "https://deepmind.google/blog/rss.xml")

        kr36 = by_id["kr36"]
        self.assertEqual(kr36.url, "https://www.36kr.com/feed")

        # urllib does not follow 308 redirects, so the URL must not have the
        # trailing slash that venturebeat permanently redirects away from
        venturebeat = by_id["venturebeat_ai"]
        self.assertEqual(venturebeat.url, "https://venturebeat.com/category/ai/feed")

        for expected_id in [
            "google_ai_blog",
            "microsoft_research",
            "bair_blog",
            "simon_willison",
            "mit_tech_review_ai",
            "techcrunch_ai",
            "venturebeat_ai",
            "the_decoder",
            "verge_ai",
            "nvidia_blog",
            "aws_ml_blog",
            "qwen_blog",
            "ifanr",
            "kr36",
            "sspai",
            "infoq_cn",
        ]:
            self.assertIn(expected_id, by_id)

        self.assertGreaterEqual(len(sources), 25)
        self.assertEqual(len({source.id for source in sources}), len(sources))
        chinese_sources = [source for source in sources if source.language == "zh"]
        self.assertGreaterEqual(len(chinese_sources), 5)


    def test_sources_round_trip_to_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sources.json"
            save_sources(path, default_sources())

            loaded = load_sources(path)

        self.assertEqual(loaded[0].id, "openai_blog")
        self.assertEqual(loaded[0].tier, "T1")


if __name__ == "__main__":
    unittest.main()

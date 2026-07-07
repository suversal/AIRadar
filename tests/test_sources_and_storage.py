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
        self.assertIn("jiqizhixin", source_ids)
        self.assertIn("ithome", source_ids)
        self.assertTrue(any(source.source_role == "authority" for source in sources))
        self.assertTrue(any(source.source_role == "signal" for source in sources))

        ithome = next(source for source in sources if source.id == "ithome")
        self.assertEqual(ithome.url, "https://www.ithome.com/rss/")
        self.assertEqual(ithome.language, "zh")
        self.assertTrue(ithome.config["extract_original_content"])

    def test_sources_round_trip_to_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sources.json"
            save_sources(path, default_sources())

            loaded = load_sources(path)

        self.assertEqual(loaded[0].id, "openai_blog")
        self.assertEqual(loaded[0].tier, "T1")


if __name__ == "__main__":
    unittest.main()

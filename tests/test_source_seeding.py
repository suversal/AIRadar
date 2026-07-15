import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.models.domain import Source
from app.services.refresh_service import _load_or_seed_sources
from app.storage.json_store import save_sources


class SourceSeedingTests(unittest.TestCase):
    def test_existing_source_file_receives_new_defaults_without_overwriting_existing_source(self):
        custom = Source(
            id="openai_blog",
            name="Custom OpenAI Name",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://custom.example/feed.xml",
            homepage="https://custom.example",
            allowed_domains=["custom.example"],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sources.json"
            save_sources(path, [custom])

            loaded = _load_or_seed_sources(path)

        by_id = {source.id: source for source in loaded}
        self.assertEqual(by_id["openai_blog"].name, "Custom OpenAI Name")
        self.assertIn("aihot_feed", by_id)
        self.assertIn("telegram_zaihuapd", by_id)
        self.assertIn("telegram_xhqcankao", by_id)
        self.assertIn("telegram_dnspodt", by_id)


if __name__ == "__main__":
    unittest.main()

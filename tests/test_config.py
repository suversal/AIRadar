import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.core.config import load_env_file


class ConfigTests(unittest.TestCase):
    def test_load_env_file_sets_missing_values_without_overriding_existing_env(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "AI_PROVIDER=kimi",
                        "KIMI_MODEL='kimi-test'",
                        "DATABASE_URL=postgresql://from-file",
                        "IGNORED_LINE",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"DATABASE_URL": "postgresql://existing"}, clear=True):
                loaded = load_env_file(env_path)

                self.assertEqual(os.environ["AI_PROVIDER"], "kimi")
                self.assertEqual(os.environ["KIMI_MODEL"], "kimi-test")
                self.assertEqual(os.environ["DATABASE_URL"], "postgresql://existing")
                self.assertEqual(loaded["DATABASE_URL"], "postgresql://from-file")


if __name__ == "__main__":
    unittest.main()

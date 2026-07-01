import importlib
import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))


class APIMainTests(unittest.TestCase):
    def test_main_module_imports_without_fastapi_installed(self):
        module = importlib.import_module("app.main")

        self.assertTrue(hasattr(module, "create_app"))
        self.assertTrue(hasattr(module, "app"))


if __name__ == "__main__":
    unittest.main()


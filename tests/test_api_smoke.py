import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.api.smoke import format_api_smoke_results, run_api_smoke_checks


class APISmokeTests(unittest.TestCase):
    def test_api_smoke_checks_health_latest_and_daily(self):
        calls = []

        def fetch_json(url):
            calls.append(url)
            if url.endswith("/health"):
                return {"status": "ok"}
            if url.endswith("/api/public/latest"):
                return {"updated_at": "2026-07-02T09:00:00+00:00", "items": [{"event_id": "c1"}]}
            if url.endswith("/api/public/daily/2026-07-02"):
                return {"report_date": "2026-07-02", "article_count": 12, "items": [{}]}
            raise AssertionError(f"unexpected url: {url}")

        results = run_api_smoke_checks(
            "http://127.0.0.1:8000",
            report_date="2026-07-02",
            fetch_json=fetch_json,
        )

        self.assertEqual([result.name for result in results], ["health", "latest", "daily"])
        self.assertTrue(all(result.ok for result in results))
        self.assertEqual(
            calls,
            [
                "http://127.0.0.1:8000/health",
                "http://127.0.0.1:8000/api/public/latest",
                "http://127.0.0.1:8000/api/public/daily/2026-07-02",
            ],
        )

    def test_api_smoke_reports_bad_latest_payload(self):
        def fetch_json(url):
            if url.endswith("/health"):
                return {"status": "ok"}
            if url.endswith("/api/public/latest"):
                return {"items": []}
            return {"report_date": "2026-07-02", "article_count": 0, "items": []}

        results = run_api_smoke_checks(
            "http://127.0.0.1:8000/",
            report_date="2026-07-02",
            fetch_json=fetch_json,
        )
        output = format_api_smoke_results(results)

        self.assertFalse(results[1].ok)
        self.assertIn("[FAIL] latest", output)
        self.assertIn("no items", output)


if __name__ == "__main__":
    unittest.main()

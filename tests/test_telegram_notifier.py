import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.services.telegram_notifier import format_sync_report, send_telegram_message


class FormatSyncReportTests(unittest.TestCase):
    def test_success_report_shows_funnel_and_sorted_failed_sources_first(self):
        text = format_sync_report(
            status="succeeded",
            report_date="2026-07-12",
            raw_count=200,
            duplicate_count=144,
            non_ai_dropped_count=5,
            new_raw_count=51,
            new_selected_count=8,
            cluster_count=12,
            source_report={
                "reddit_machinelearning": {
                    "status": "failed",
                    "error": "HTTP Error 429: Too Many Requests",
                    "fetched_count": 0,
                    "accepted_count": 0,
                },
                "google_developers_blog": {
                    "status": "ok",
                    "error": None,
                    "fetched_count": 20,
                    "accepted_count": 3,
                    "ingested_count": 3,
                },
                "aihot_all": {
                    "status": "ok",
                    "error": None,
                    "fetched_count": 40,
                    "accepted_count": 6,
                    "ingested_count": 12,
                },
                "quiet_source": {
                    "status": "ok",
                    "error": None,
                    "fetched_count": 0,
                    "accepted_count": 0,
                    "ingested_count": 0,
                },
            },
            source_names={
                "reddit_machinelearning": "Reddit r/MachineLearning",
                "google_developers_blog": "Google Developers Blog",
                "aihot_all": "AI HOT 全部AI动态",
            },
        )

        # 恒等式在消息里可核对
        self.assertIn("200", text)
        self.assertIn("144", text)
        self.assertIn("入库 51", text)
        self.assertIn("精选 8", text)
        # 每个信源明细行同时给出入库/精选/抓取三个数,不再只报"入选"
        self.assertIn("AI HOT 全部AI动态：入库 12 · 精选 6 / 抓取 40", text)
        self.assertIn("Google Developers Blog：入库 3 · 精选 3 / 抓取 20", text)
        # 失败源必须在成功源之前出现,且用改过的名称而非 id
        failed_pos = text.index("Reddit r/MachineLearning")
        aihot_pos = text.index("AI HOT 全部AI动态")
        google_pos = text.index("Google Developers Blog")
        self.assertLess(failed_pos, aihot_pos)
        self.assertLess(failed_pos, google_pos)
        # 错误原文要带出来
        self.assertIn("429", text)
        # 按入库数降序:aihot(12) 排在 google(3) 前面
        self.assertLess(aihot_pos, google_pos)
        # 本轮完全没抓到东西的源不再单独占一行,归进底部汇总
        self.assertNotIn("quiet_source：", text)
        self.assertIn("本轮无抓取（1）：quiet_source", text)

    def test_failure_report_surfaces_error_prominently(self):
        text = format_sync_report(
            status="failed",
            report_date="2026-07-12",
            error="db connection refused",
        )
        self.assertIn("失败", text)
        self.assertIn("db connection refused", text)

    def test_unnamed_source_falls_back_to_id(self):
        text = format_sync_report(
            status="succeeded",
            report_date="2026-07-12",
            source_report={"mystery_source": {"status": "ok", "accepted_count": 1, "fetched_count": 1}},
        )
        self.assertIn("mystery_source", text)


class SendTelegramMessageTests(unittest.TestCase):
    def test_posts_expected_payload_when_credentials_present(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"ok": true}'

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["data"] = request.data
            return FakeResponse()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = send_telegram_message(
                "hello world", bot_token="tok123", chat_id="chat456"
            )

        self.assertTrue(result)
        self.assertIn("tok123", captured["url"])
        self.assertIn(b"chat456", captured["data"])
        self.assertIn(b"hello", captured["data"])

    def test_returns_false_without_credentials(self):
        with patch.dict("os.environ", {}, clear=True):
            result = send_telegram_message("hi", bot_token=None, chat_id=None)
        self.assertFalse(result)

    def test_swallows_network_exceptions(self):
        with patch("urllib.request.urlopen", side_effect=RuntimeError("boom")):
            result = send_telegram_message("hi", bot_token="t", chat_id="c")
        self.assertFalse(result)

    def test_truncates_overlong_messages(self):
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'{"ok": true}'

        def fake_urlopen(request, timeout=None):
            captured["data"] = request.data
            return FakeResponse()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            send_telegram_message("x" * 5000, bot_token="t", chat_id="c")

        # Telegram 硬限制 4096 字符,url-encoded 后原文长度必须被截断
        self.assertLess(len(captured["data"]), 5000 * 3)


if __name__ == "__main__":
    unittest.main()

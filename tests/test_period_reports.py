from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.services.period_summary_service import (
    build_period_report,
    parse_period_summary_payload,
    period_key_for,
    period_range_for_key,
)
from app.services.ai_service import FakeAIProvider


def make_item(
    title,
    *,
    category="model",
    score=80.0,
    summary="一句话摘要。",
    source_count=1,
    source_id="src-a",
    category_label=None,
):
    return {
        "event_id": f"e-{title[:6]}",
        "title": title,
        "category": category,
        "category_label": category_label or category,
        "one_line_summary": summary,
        "final_score": score,
        "source_count": source_count,
        "main_source": {"id": source_id, "name": source_id, "url": "", "tier": "core"},
    }


class PeriodKeyTests(unittest.TestCase):
    def test_weekly_key_uses_iso_week(self):
        self.assertEqual(period_key_for("weekly", date(2026, 7, 10)), "2026-W28")
        # ISO year boundary: 2024-12-30 belongs to 2025-W01
        self.assertEqual(period_key_for("weekly", date(2024, 12, 30)), "2025-W01")

    def test_monthly_key_is_year_month(self):
        self.assertEqual(period_key_for("monthly", date(2026, 7, 10)), "2026-07")

    def test_period_range_for_key_round_trips(self):
        start, end = period_range_for_key("weekly", "2026-W28")
        self.assertEqual(start, date(2026, 7, 6))
        self.assertEqual(end, date(2026, 7, 12))

        start, end = period_range_for_key("monthly", "2026-07")
        self.assertEqual(start, date(2026, 7, 1))
        self.assertEqual(end, date(2026, 7, 31))

    def test_period_range_rejects_bad_keys(self):
        with self.assertRaises(ValueError):
            period_range_for_key("weekly", "2026-13")
        with self.assertRaises(ValueError):
            period_range_for_key("monthly", "2026-W02")


class PeriodSummaryTests(unittest.TestCase):
    def test_parse_period_summary_payload_validates_fields(self):
        payload = parse_period_summary_payload(
            {
                "mainline_title": "智能体落地成为本周主线",
                "mainline_body": "本周动态围绕……",
                "theme_notes": [{"label": "模型", "note": "多家发布"}, "bad"],
            }
        )

        self.assertEqual(payload["mainline_title"], "智能体落地成为本周主线")
        self.assertEqual(payload["theme_notes"], [{"label": "模型", "note": "多家发布"}])

        with self.assertRaises(ValueError):
            parse_period_summary_payload({"mainline_title": "只有标题"})

    def test_build_period_report_uses_ai_summary_and_metadata(self):
        items = [make_item(f"事件{i}", score=90 - i) for i in range(3)]

        report = build_period_report(
            kind="weekly",
            anchor=date(2026, 7, 10),
            items=items,
            report_dates=["2026-07-09", "2026-07-10"],
            ai_provider=FakeAIProvider(),
        )

        self.assertEqual(report["kind"], "weekly")
        self.assertEqual(report["period_key"], "2026-W28")
        self.assertEqual(report["range_start"], "2026-07-06")
        self.assertEqual(report["range_end"], "2026-07-12")
        self.assertEqual(report["article_count"], 3)
        self.assertEqual(report["report_dates"], ["2026-07-09", "2026-07-10"])
        self.assertTrue(report["mainline_title"])
        self.assertTrue(report["mainline_body"])
        self.assertEqual(report["status"], "generated")

    def test_build_period_report_freezes_entries_snapshot_ordered_by_score(self):
        items = [
            make_item("事件A", score=70.0),
            make_item("事件B", score=95.0),
            make_item("事件C", score=80.0),
        ]

        report = build_period_report(
            kind="weekly",
            anchor=date(2026, 7, 10),
            items=items,
            report_dates=["2026-07-10"],
            ai_provider=FakeAIProvider(),
        )

        self.assertEqual(
            [entry["event_id"] for entry in report["entries"]],
            ["e-事件B", "e-事件C", "e-事件A"],
        )
        self.assertEqual(report["entries"][0]["score_at_selection"], 95.0)
        # content fields must never be frozen into the entries snapshot -
        # they are always resolved live from event_id at read time
        for entry in report["entries"]:
            self.assertNotIn("title", entry)
            self.assertNotIn("summary", entry)

    def test_build_period_report_computes_stats_snapshot(self):
        items = [
            make_item("事件A", score=90, source_count=3, source_id="src-a", category_label="模型"),
            make_item("事件B", score=80, source_count=1, source_id="src-b", category_label="模型"),
            make_item("事件C", score=70, source_count=1, source_id="src-a", category_label="产品"),
        ]

        report = build_period_report(
            kind="weekly",
            anchor=date(2026, 7, 10),
            items=items,
            report_dates=["2026-07-10"],
            ai_provider=FakeAIProvider(),
        )

        stats = report["stats"]
        self.assertEqual(stats["source_coverage_count"], 2)
        self.assertAlmostEqual(stats["multi_source_ratio"], 1 / 3)
        self.assertEqual(stats["category_distribution"], {"模型": 2, "产品": 1})

    def test_build_period_report_marks_fallback_on_provider_failure(self):
        class BoomProvider(FakeAIProvider):
            def summarize_period(self, items, kind, range_label):
                raise RuntimeError("provider down")

        report = build_period_report(
            kind="monthly",
            anchor=date(2026, 7, 10),
            items=[make_item("事件A")],
            report_dates=["2026-07-10"],
            ai_provider=BoomProvider(),
        )

        self.assertEqual(report["status"], "fallback")
        self.assertTrue(report["mainline_title"])  # deterministic fallback text


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.services.ai_service import FakeAIProvider
from app.services.daily_summary_service import (
    build_daily_summary,
    build_summary_input,
    group_by_focus_category,
    parse_daily_summary_payload,
    sort_daily_items,
    summary_digest,
)


def make_item(title, *, score=80.0, source_count=1, focus="model"):
    return {
        "event_id": f"e-{title}",
        "title": title,
        "final_score": score,
        "source_count": source_count,
        "focus_category": focus,
        "one_line_summary": f"{title}的一句话摘要。",
    }


class DailyOrderingTests(unittest.TestCase):
    def test_multi_source_group_leads_but_score_orders_within_it(self):
        """「被多家报道」决定进哪一组，组内仍然由分数说了算。

        真实案例（2026-08-18 行业动态）：3 个信源 60.5 分的 Anthropic IPO
        不应该排在 2 个信源 89.1 分的英伟达担保之前——按 (信源数, 分数)
        整体降序就会这样，所以这里刻意不那么排。
        """
        items = [
            make_item("三源低分", score=60.5, source_count=3),
            make_item("双源高分", score=89.1, source_count=2),
            make_item("单源最高", score=95.0, source_count=1),
            make_item("单源次高", score=90.0, source_count=1),
        ]

        self.assertEqual(
            [item["title"] for item in sort_daily_items(items)],
            ["双源高分", "三源低分", "单源最高", "单源次高"],
        )

    def test_all_single_source_falls_back_to_plain_score_order(self):
        items = [make_item("低", score=61.0), make_item("高", score=93.0)]

        self.assertEqual([item["title"] for item in sort_daily_items(items)], ["高", "低"])


class DailyCategoryGroupingTests(unittest.TestCase):
    def test_groups_follow_the_fixed_taxonomy_order(self):
        items = [
            make_item("教程", focus="tutorial"),
            make_item("模型", focus="model"),
            make_item("行业", focus="industry"),
        ]

        self.assertEqual(
            [key for key, _label, _items in group_by_focus_category(items)],
            ["model", "industry", "tutorial"],
        )

    def test_categories_with_no_items_are_absent(self):
        """空分类不出现——页面照这个列表渲染，所以不会留下空壳板块。

        2026-08-16 的 model 分类当天一条都没有，2026-08-17 没有 tutorial。
        """
        groups = group_by_focus_category([make_item("只有模型", focus="model")])

        self.assertEqual([key for key, _label, _items in groups], ["model"])

    def test_group_items_use_the_daily_ordering(self):
        items = [
            make_item("单源高", score=95.0, source_count=1),
            make_item("双源低", score=70.0, source_count=2),
        ]

        _key, _label, group = group_by_focus_category(items)[0]
        self.assertEqual([item["title"] for item in group], ["双源低", "单源高"])


class DailySummaryInputTests(unittest.TestCase):
    def test_mainline_material_is_multi_source_only(self):
        items = [
            make_item("双源", source_count=2),
            make_item("单源", source_count=1),
        ]

        summary_input = build_summary_input(items)

        self.assertEqual(
            [event["title"] for event in summary_input["mainline_events"]], ["双源"]
        )
        # 分类简述看的是全类，不是只看多信源——两块内容的取材范围不同，
        # 才不会在同一页把同几条事讲两遍
        self.assertEqual(summary_input["categories"][0]["item_count"], 2)

    def test_digest_ignores_ordering_of_equal_material(self):
        items = [make_item("甲", source_count=2), make_item("乙", source_count=2)]

        self.assertEqual(
            summary_digest(build_summary_input(items)),
            summary_digest(build_summary_input(list(reversed(items)))),
        )

    def test_digest_changes_when_an_event_is_added(self):
        base = [make_item("甲", source_count=2)]
        grown = base + [make_item("乙", source_count=2)]

        self.assertNotEqual(
            summary_digest(build_summary_input(base)),
            summary_digest(build_summary_input(grown)),
        )


class DailySummaryPayloadTests(unittest.TestCase):
    def test_unknown_category_keys_are_dropped(self):
        parsed = parse_daily_summary_payload(
            {
                "mainline_title": "标题",
                "mainline_body": "正文",
                "category_notes": [
                    {"category": "model", "note": "模型动向"},
                    {"category": "编不出来的分类", "note": "幻觉"},
                ],
            }
        )

        self.assertEqual([note["category"] for note in parsed["category_notes"]], ["model"])
        self.assertEqual(parsed["category_notes"][0]["label"], "模型动态")

    def test_missing_mainline_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_daily_summary_payload({"mainline_title": "只有标题", "mainline_body": ""})


class DailySummaryBuildTests(unittest.TestCase):
    def test_day_without_multi_source_events_gets_no_mainline(self):
        """没有多信源事件就不写主线，而不是编一段。2026-08-01/02 就是这种天。"""
        summary = build_daily_summary(
            report_date=date(2026, 8, 2),
            items=[make_item("孤例", source_count=1)],
            ai_provider=FakeAIProvider(),
        )

        self.assertEqual(summary["status"], "skipped")
        self.assertEqual(summary["mainline_title"], "")
        self.assertEqual(summary["category_notes"], [])

    def test_unchanged_material_returns_none_instead_of_paying_again(self):
        """流水线一天跑 12-14 次，素材没变就不该再买一遍同样的文字。"""
        items = [make_item("双源", source_count=2)]
        first = build_daily_summary(
            report_date=date(2026, 8, 18), items=items, ai_provider=FakeAIProvider()
        )

        second = build_daily_summary(
            report_date=date(2026, 8, 18),
            items=items,
            ai_provider=FakeAIProvider(),
            previous_digest=first["digest"],
        )

        self.assertEqual(first["status"], "generated")
        self.assertIsNone(second)

    def test_changed_material_regenerates(self):
        first = build_daily_summary(
            report_date=date(2026, 8, 18),
            items=[make_item("双源", source_count=2)],
            ai_provider=FakeAIProvider(),
        )

        second = build_daily_summary(
            report_date=date(2026, 8, 18),
            items=[make_item("双源", source_count=2), make_item("新双源", source_count=2)],
            ai_provider=FakeAIProvider(),
            previous_digest=first["digest"],
        )

        self.assertIsNotNone(second)
        self.assertEqual(second["status"], "generated")

    def test_provider_failure_leaves_no_mainline_rather_than_fallback_text(self):
        """日报不做确定性兜底：头条就在下面的列表里，复述一遍只是噪声。
        （周月报保留兜底是另一个取舍——那里的兜底至少点出了本期头条。）"""

        class BoomProvider(FakeAIProvider):
            def summarize_daily(self, summary_input, date_label):
                raise RuntimeError("provider down")

        summary = build_daily_summary(
            report_date=date(2026, 8, 18),
            items=[make_item("双源", source_count=2)],
            ai_provider=BoomProvider(),
        )

        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["mainline_body"], "")


if __name__ == "__main__":
    unittest.main()

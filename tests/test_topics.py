from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.services.topics import (
    TOPIC_GROUPS,
    build_topic_detail_payload,
    build_topics_payload,
    group_of_topic,
    item_matches_topic,
    topic_by_id,
)

TODAY = date(2026, 8, 20)


def make_item(**overrides):
    item = {
        "event_id": "e1",
        "title": "OpenAI releases agent model",
        "category": "model",
        "tags": ["Agent"],
        "summary": "",
        "one_line_summary": "",
        "selected": True,
        "is_main": True,
        "source_count": 1,
        "published_at": "2026-08-19T06:00:00+00:00",
    }
    item.update(overrides)
    return item


class TopicRegistryTests(unittest.TestCase):
    def test_registry_has_two_groups_entities_and_directions(self):
        groups = {group["id"]: group for group in TOPIC_GROUPS}

        self.assertEqual(list(groups), ["entities", "directions"])
        self.assertGreaterEqual(len(groups["entities"]["topics"]), 15)
        self.assertGreaterEqual(len(groups["directions"]["topics"]), 8)
        # every topic id is unique across groups
        all_ids = [t["id"] for g in TOPIC_GROUPS for t in g["topics"]]
        self.assertEqual(len(all_ids), len(set(all_ids)))
        # 每个主题都要有编辑描述——索引页卡片靠它回答"为什么值得关注"
        for group in TOPIC_GROUPS:
            for topic in group["topics"]:
                self.assertTrue(topic["description"], f"{topic['id']} 缺描述")

    def test_entity_topics_merge_company_and_model_keywords(self):
        anthropic = topic_by_id("anthropic")

        # 公司名、模型名都归到同一张实体卡
        self.assertTrue(item_matches_topic(make_item(title="Anthropic 完成新一轮融资"), anthropic))
        self.assertTrue(item_matches_topic(make_item(title="Claude 5 发布"), anthropic))
        self.assertFalse(item_matches_topic(make_item(title="Gemini 3 上线"), anthropic))

    def test_legacy_four_group_ids_redirect_to_merged_topics(self):
        # 旧 /all?topic= 链接可能被外部收藏,四组时代的 id 不能静默失效
        self.assertEqual(topic_by_id("claude")["id"], "anthropic")
        self.assertEqual(topic_by_id("gpt")["id"], "openai")
        self.assertEqual(topic_by_id("claude_code")["id"], "anthropic")
        self.assertEqual(topic_by_id("robotics")["id"], "embodied")
        self.assertIsNone(topic_by_id("cn_models"))
        self.assertEqual(group_of_topic("claude")["id"], "entities")

    def test_ascii_keywords_require_word_boundaries(self):
        meta = topic_by_id("meta")

        self.assertTrue(item_matches_topic(make_item(title="Meta ships Llama 5"), meta))
        # "metadata" must not match the Meta topic
        self.assertFalse(
            item_matches_topic(make_item(title="New metadata standard for RSS"), meta)
        )

    def test_summary_mentions_no_longer_count_as_membership(self):
        # 匹配语义是"关于 X"不是"提到过 X":全文摘要里顺嘴一句不算
        anthropic = topic_by_id("anthropic")

        self.assertFalse(
            item_matches_topic(
                make_item(title="OpenAI 发布新模型", summary="评测中顺带对比了 Claude。"),
                anthropic,
            )
        )
        # 一句话提要仍参与匹配——它承载"这条主要在讲什么"
        self.assertTrue(
            item_matches_topic(
                make_item(title="新模型发布", one_line_summary="Claude 5 上线"), anthropic
            )
        )


class TopicsPayloadTests(unittest.TestCase):
    def test_payload_counts_selected_only_with_week_windows(self):
        items = [
            make_item(event_id="e1", title="Claude 5 launches", published_at="2026-08-19T06:00:00+00:00"),
            make_item(event_id="e2", title="Claude Code adds hooks", published_at="2026-08-10T06:00:00+00:00"),
            make_item(event_id="e3", title="Claude rumor", selected=False),
            make_item(event_id="e4", title="随便一条", tags=[]),
        ]

        payload = build_topics_payload(items, today=TODAY)

        self.assertEqual([g["id"] for g in payload["groups"]], ["entities", "directions"])
        entities = {t["id"]: t for t in payload["groups"][0]["topics"]}
        anthropic = entities["anthropic"]
        self.assertEqual(anthropic["count"], 2)
        self.assertEqual(anthropic["week_count"], 1)  # 8-19 落在近 7 天窗口
        self.assertEqual(anthropic["prev_week_count"], 1)  # 8-10 落在上一个 7 天窗口
        self.assertEqual(anthropic["latest_published_at"], "2026-08-19")
        # article_count 是精选口径
        self.assertEqual(payload["article_count"], 3)


class TopicDetailPayloadTests(unittest.TestCase):
    def test_detail_separates_archive_counts_from_selected_timeline(self):
        items = [
            make_item(event_id="e1", title="Claude 5 launches"),
            make_item(event_id="e2", title="Claude rumor", selected=False),
            make_item(event_id="e3", title="OpenAI news"),
        ]

        payload = build_topic_detail_payload("anthropic", items, today=TODAY)

        self.assertEqual(payload["topic"]["name"], "Anthropic / Claude")
        self.assertEqual(payload["total_count"], 2)
        self.assertEqual(payload["selected_count"], 1)
        self.assertEqual([i["event_id"] for i in payload["items"]], ["e1"])

    def test_detail_focus_requires_recent_multi_source_main_items(self):
        items = [
            # 多源、近 14 天、代表条 → 进焦点
            make_item(event_id="hot", title="Claude 5 launches", source_count=4),
            # 单源 → 不进焦点
            make_item(event_id="single", title="Claude tips", published_at="2026-08-18T06:00:00+00:00"),
            # 多源但超出 14 天窗口 → 不进焦点
            make_item(
                event_id="old",
                title="Claude 4.5 recap",
                source_count=3,
                published_at="2026-07-20T06:00:00+00:00",
            ),
            # 多源但不是事件代表条 → 不进焦点(避免同一事件刷屏)
            make_item(
                event_id="member",
                title="Claude 5 独家解读",
                source_count=4,
                is_main=False,
            ),
        ]

        payload = build_topic_detail_payload("anthropic", items, today=TODAY)

        self.assertEqual([i["event_id"] for i in payload["focus"]], ["hot"])

    def test_detail_paginates_selected_timeline(self):
        items = [
            make_item(
                event_id=f"e{n}",
                title=f"Claude update {n}",
                published_at=f"2026-08-{10 + n:02d}T06:00:00+00:00",
            )
            for n in range(1, 6)
        ]

        payload = build_topic_detail_payload("anthropic", items, today=TODAY, limit=2, offset=2)

        self.assertEqual(payload["selected_count"], 5)
        # 时间线按发布时间倒序:全序列 e5..e1,offset=2 取 e3、e2
        self.assertEqual([i["event_id"] for i in payload["items"]], ["e3", "e2"])

    def test_detail_returns_none_for_unknown_topic(self):
        self.assertIsNone(build_topic_detail_payload("nope", [], today=TODAY))


if __name__ == "__main__":
    unittest.main()

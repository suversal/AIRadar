from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.services.topics import (
    TOPIC_GROUPS,
    build_topics_payload,
    item_matches_topic,
    topic_by_id,
)


def make_item(**overrides):
    item = {
        "event_id": "e1",
        "title": "OpenAI releases agent model",
        "category": "model",
        "tags": ["Agent"],
        "summary": "",
        "one_line_summary": "",
    }
    item.update(overrides)
    return item


class TopicRegistryTests(unittest.TestCase):
    def test_registry_has_three_groups_with_reasonable_sizes(self):
        groups = {group["id"]: group for group in TOPIC_GROUPS}

        self.assertEqual(
            list(groups), ["companies", "directions", "formats"]
        )
        self.assertGreaterEqual(len(groups["companies"]["topics"]), 10)
        self.assertGreaterEqual(len(groups["directions"]["topics"]), 8)
        self.assertEqual(len(groups["formats"]["topics"]), 5)
        # every topic id is unique across groups
        all_ids = [t["id"] for g in TOPIC_GROUPS for t in g["topics"]]
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_title_and_tag_keywords_match_company_topics(self):
        openai = topic_by_id("openai")
        anthropic = topic_by_id("anthropic")

        self.assertTrue(item_matches_topic(make_item(), openai))
        self.assertFalse(item_matches_topic(make_item(), anthropic))
        self.assertTrue(
            item_matches_topic(
                make_item(title="新模型发布", tags=["Claude"]), anthropic
            )
        )

    def test_ascii_keywords_require_word_boundaries(self):
        meta = topic_by_id("meta")

        self.assertTrue(item_matches_topic(make_item(title="Meta ships Llama 5"), meta))
        # "metadata" must not match the Meta topic
        self.assertFalse(
            item_matches_topic(make_item(title="New metadata standard for RSS"), meta)
        )

    def test_chinese_keywords_match_by_substring(self):
        multimodal = topic_by_id("multimodal")

        self.assertTrue(
            item_matches_topic(make_item(summary="该模型支持多模态输入。"), multimodal)
        )

    def test_format_topics_match_by_display_category(self):
        research_format = topic_by_id("format_research")

        self.assertTrue(
            item_matches_topic(make_item(category="research", title="随便"), research_format)
        )
        self.assertFalse(
            item_matches_topic(make_item(category="model", title="随便"), research_format)
        )


class TopicsPayloadTests(unittest.TestCase):
    def test_payload_groups_topics_with_counts(self):
        items = [
            make_item(event_id="e1", title="OpenAI releases agent model", tags=["Agent"]),
            make_item(event_id="e2", title="Claude 5 launches", tags=[]),
            make_item(event_id="e3", title="随便", category="research"),
        ]

        payload = build_topics_payload(items)

        self.assertEqual([g["id"] for g in payload["groups"]], ["companies", "directions", "formats"])
        companies = payload["groups"][0]
        by_id = {t["id"]: t for t in companies["topics"]}
        self.assertEqual(by_id["openai"]["count"], 1)
        self.assertEqual(by_id["anthropic"]["count"], 1)
        self.assertEqual(by_id["openai"]["name"], "OpenAI")
        formats = payload["groups"][2]
        research = next(t for t in formats["topics"] if t["id"] == "format_research")
        self.assertEqual(research["count"], 1)
        self.assertEqual(payload["article_count"], 3)


if __name__ == "__main__":
    unittest.main()

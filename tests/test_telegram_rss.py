import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.crawlers.telegram_rss import (
    TelegramDescriptionParser,
    TelegramRSSCrawler,
    parse_telegram_rss,
)
from app.models.domain import Source
from app.services.daily_report_service import _clean_original_blocks


def telegram_source(**config):
    return Source(
        id="telegram_test",
        name="测试频道",
        source_role="aggregator",
        tier="T3",
        type="telegram_rss",
        category="community",
        url="https://rsshub.app/telegram/channel/testchannel",
        homepage="https://t.me/testchannel",
        allowed_domains=["t.me", "telegram.me"],
        language="zh",
        can_be_main_source=False,
        config={"channel": "testchannel", **config},
    )


class TelegramDescriptionParserTests(unittest.TestCase):
    def test_preserves_reply_sources_updates_and_hero_image_without_signatures(self):
        html = """
        <div class="rsshub-quote"><blockquote>
          <p><a href="https://t.me/testchannel/40"><b>测试频道</b>:</a></p>
          <p>旧消息正文<br><br>来源：<a href="https://old.example/story">旧来源</a></p>
        </blockquote></div>
        <p><b>测试标题</b><br><br>
          正文提到 <a href="http://t.you/" onclick="evil()">t.you</a>，但它不是文章来源。<br><br>
          <a href="https://reuters.example/a">Reuters</a> |
          <a href="https://bloomberg.example/b">Bloomberg</a><br><br>
          🌸 <a href="https://t.me/testchannel">测试频道</a> ·
          <a href="https://t.me/testchat">茶馆群</a> ·
          <a href="https://t.me/testbot">投稿通道</a>
        </p>
        <blockquote>update2：补充内容<br><br>来源：<a href="https://update.example/c">更新来源</a></blockquote>
        <img src="https://cdn5.telesco.pe/file/example.jpg" onclick="evil()">
        """

        parsed = TelegramDescriptionParser(
            base_url="https://t.me/testchannel/42", title="测试标题"
        ).parse(html)
        blocks = parsed["original_blocks"]

        self.assertEqual(
            [(block["type"], block.get("kind")) for block in blocks],
            [
                ("quote", "reply"),
                ("image", None),
                ("paragraph", None),
                ("source_list", None),
                ("quote", "update"),
            ],
        )
        self.assertEqual(blocks[0]["author"], "测试频道")
        self.assertEqual(blocks[0]["source_url"], "https://t.me/testchannel/40")
        reply_sources = [
            child for child in blocks[0]["children"] if child["type"] == "source_list"
        ]
        self.assertEqual(reply_sources[0]["links"][0]["host"], "old.example")
        self.assertEqual(
            [link["label"] for link in blocks[3]["links"]], ["Reuters", "Bloomberg"]
        )
        self.assertNotIn("t.you", [link["host"] for link in blocks[3]["links"]])
        update_sources = [
            child for child in blocks[4]["children"] if child["type"] == "source_list"
        ]
        self.assertEqual(update_sources[0]["links"][0]["host"], "update.example")
        self.assertEqual(blocks[1]["fallback_url"], "https://t.me/testchannel/42")
        self.assertNotIn("onclick", str(blocks))
        self.assertIn("t.you", blocks[2]["html"])
        self.assertNotIn("投稿通道", str(blocks))

    def test_unsafe_links_are_plain_text_and_nested_quotes_stop_at_four_levels(self):
        nested = "内容"
        for _ in range(6):
            nested = f"<blockquote>{nested}</blockquote>"
        html = f'<p><a href="javascript:alert(1)">危险链接</a></p>{nested}'

        blocks = TelegramDescriptionParser(
            base_url="https://t.me/testchannel/50", title="另一标题"
        ).parse(html)["original_blocks"]

        self.assertNotIn("javascript:", str(blocks))

        def quote_depth(values, depth=0):
            return max(
                [depth]
                + [
                    quote_depth(block.get("children", []), depth + 1)
                    for block in values
                    if block.get("type") == "quote"
                ]
            )

        self.assertLessEqual(quote_depth(blocks), 4)

    def test_recursive_blocks_survive_report_sanitization(self):
        blocks = [
            {
                "type": "quote",
                "kind": "reply",
                "author": "测试频道",
                "source_url": "https://t.me/testchannel/1",
                "children": [
                    {
                        "type": "source_list",
                        "links": [
                            {"label": "来源", "url": "https://example.com/a", "host": "example.com"},
                            {"label": "危险", "url": "javascript:alert(1)", "host": ""},
                        ],
                    }
                ],
            },
            {
                "type": "image",
                "url": "https://cdn5.telesco.pe/file/a.jpg",
                "fallback_url": "https://t.me/testchannel/2",
            },
            {
                "type": "signature",
                "name": "🌸 测试频道 · 茶馆水群 · 投稿通道",
                "links": [
                    {"label": "测试频道", "url": "https://t.me/testchannel", "host": "t.me"}
                ],
            },
            {
                "type": "paragraph",
                "text": "有效正文 MacRumors 🌸 测试频道 · 茶馆水群 · 投稿通道",
            },
        ]

        cleaned = _clean_original_blocks(blocks, strip_telegram_signatures=True)

        self.assertEqual(cleaned[0]["children"][0]["links"][0]["url"], "https://example.com/a")
        self.assertEqual(len(cleaned[0]["children"][0]["links"]), 1)
        self.assertEqual(cleaned[1]["fallback_url"], "https://t.me/testchannel/2")
        self.assertEqual([block["type"] for block in cleaned], ["quote", "image", "paragraph"])
        self.assertEqual(cleaned[2]["text"], "有效正文 MacRumors")

    def test_video_blocks_require_safe_providers_and_https_urls(self):
        blocks = [
            {
                "type": "video",
                "provider": "youtube",
                "url": "https://www.youtube-nocookie.com/embed/xJ94HFpGM4Y",
                "title": "Safe embed",
            },
            {
                "type": "video",
                "provider": "youtube",
                "url": "https://untrusted.example/embed/xJ94HFpGM4Y",
            },
            {
                "type": "video",
                "provider": "file",
                "url": "https://cdn.example/animation.webm",
                "mime_type": "video/webm",
                "autoplay": True,
                "muted": True,
            },
            {
                "type": "video",
                "provider": "file",
                "url": "http://cdn.example/insecure.mp4",
                "mime_type": "video/mp4",
            },
        ]

        cleaned = _clean_original_blocks(blocks)

        self.assertEqual(len(cleaned), 2)
        self.assertEqual(cleaned[0]["provider"], "youtube")
        self.assertEqual(cleaned[1]["provider"], "file")
        self.assertTrue(cleaned[1]["autoplay"])
        self.assertTrue(cleaned[1]["muted"])

    def test_x_embed_sanitization_keeps_safe_card_and_rejects_other_hosts(self):
        safe = {
            "type": "social_embed",
            "provider": "x",
            "url": "https://x.com/Kimi_Moonshot/status/2077521842080817296",
            "author_name": "Kimi.ai",
            "username": "Kimi_Moonshot",
            "avatar_url": "https://pbs.substack.com/profile.jpg",
            "video_url": "https://video.twimg.com/media/demo.mp4",
            "video_mime_type": "video/mp4",
            "like_count": 11466,
        }

        cleaned = _clean_original_blocks(
            [
                safe,
                {
                    **safe,
                    "url": "https://untrusted.example/status/2077521842080817296",
                },
                {
                    **safe,
                    "video_url": "http://video.twimg.com/media/insecure.mp4",
                },
            ]
        )

        self.assertEqual(len(cleaned), 2)
        self.assertEqual(cleaned[0], safe)
        self.assertNotIn("video_url", cleaned[1])
        self.assertNotIn("video_mime_type", cleaned[1])


class TelegramRSSCrawlerTests(unittest.TestCase):
    XML = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><title>测试</title><item>
      <title>🖼 测试标题</title>
      <description><![CDATA[<p><b>🖼 测试标题</b><br><br>正文</p>]]></description>
      <link>https://t.me/testchannel/42</link>
      <guid isPermaLink="false">https://t.me/testchannel/42</guid>
    </item></channel></rss>"""

    def test_parse_uses_item_link_and_marks_missing_pubdate(self):
        article = parse_telegram_rss(
            self.XML,
            telegram_source(),
            rsshub_instance="https://working.example",
        )[0]

        self.assertEqual(article.title, "🖼 测试标题")
        self.assertEqual(article.source_url, "https://t.me/testchannel/42")
        self.assertEqual(article.content, "正文")
        self.assertTrue(article.metadata["rss_pubdate_missing"])
        self.assertEqual(article.metadata["content_origin"], "telegram_rss_description")
        self.assertEqual(article.metadata["rsshub_instance"], "https://working.example")

    @patch("app.crawlers.telegram_rss.fetch_url_text")
    def test_falls_through_errors_and_non_feed_html(self, fetch_url_text):
        fetch_url_text.side_effect = [
            RuntimeError("403"),
            "<html><title>challenge</title></html>",
            self.XML,
        ]
        source = telegram_source(
            rsshub_instances=[
                "https://one.example",
                "https://two.example",
                "https://three.example/rsshub",
            ]
        )

        articles = TelegramRSSCrawler(source).fetch()

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].metadata["rsshub_instance"], "https://three.example/rsshub")
        self.assertEqual(fetch_url_text.call_count, 3)
        self.assertEqual(
            fetch_url_text.call_args_list[-1].args[0],
            "https://three.example/rsshub/telegram/channel/testchannel",
        )


if __name__ == "__main__":
    unittest.main()

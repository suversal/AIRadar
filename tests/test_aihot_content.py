import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.crawlers.aihot_content import (
    AIHOT_USER_AGENT,
    _assign_original_and_translation,
    _decode_flight_chunk,
    _extract_chinese_body_html,
    _extract_english_original_html,
    fetch_aihot_item_content,
)
from app.crawlers.article_content import extract_article_content

# Trimmed-down but structurally faithful reproduction of a real
# https://aihot.virxact.com/items/{id} page, captured 2026-07-13:
# - Chinese translation is plain, visible DOM inside .dt-body > .dt-article
# - English original is embedded (never fetched separately) as a Next.js RSC
#   flight chunk: <script>self.__next_f.push([1,"<JSON-escaped HTML>"])</script>
_ENGLISH_HTML = (
    r"<h2>Key Points</h2> "
    r"<p>A German research consortium has released the open-source language model "
    r"Soofi S, which was trained entirely on Deutsche Telekom AI cloud infrastructure.</p> "
    r"<p>The model uses a resource efficient hybrid architecture that activates only a fraction "
    r"of its parameters per generated token, keeping throughput steady even for very long inputs.</p> "
    r"<h2>Benchmarks</h2> "
    r"<p>Because the training data leaned heavily German the model beats other fully open models "
    r"on German English and coding benchmarks including HumanEval and MBPP scores that lead the field.</p>"
)

# a decoy chunk: short, mostly non-Latin, must NOT be picked as the English body
_DECOY_HTML = r"<span>70</span>"

AIHOT_FIXTURE_HTML = f"""<!doctype html><html><head><title>test</title></head><body>
<article class="dt-detail">
  <h1 class="dt-title">德国AI协会发布开源模型Soofi S</h1>
  <div class="dt-body">
    <div class="dt-body-head"><span>正文 · AI 翻译</span></div>
    <div class="dt-article">
      <h2>关键要点</h2>
      <p>一个德国研究联盟发布了开源大语言模型 Soofi S，该模型完全在德国电信的 AI 云基础设施上完成训练。</p>
      <p>该模型采用资源高效的混合架构，每生成一个模型 token 仅激活其参数中的一小部分，即使输入极长也能保持处理速度恒定。</p>
      <figure><img src="https://example.com/chart.jpg" alt="chart"><figcaption>图注文字</figcaption></figure>
    </div>
  </div>
</article>
<script>self.__next_f.push([1,"29:T3a2e,"])</script>
<script>self.__next_f.push([1,"{_DECOY_HTML}"])</script>
<script>self.__next_f.push([1,"{_ENGLISH_HTML}"])</script>
</body></html>"""


class AihotContentTests(unittest.TestCase):
    def test_decode_flight_chunk_unescapes_real_next_js_format(self):
        # real capture from aihot.virxact.com/items/{id} (2026-07-13): the
        # RSC wire format escapes "<" and ">" as literal backslash-u003c /
        # backslash-u003e sequences, not raw angle brackets - built via
        # chr(92) here rather than typed escapes, since typing a literal
        # backslash-u sequence in this source file would just get
        # interpreted as an actual "<"/">" long before the test runs
        backslash = chr(92)
        plain = "<h2>Key Points</h2> <ul> <li>A German research consortium has released the open-source language model Soofi S.</li> </ul>"
        raw = plain.replace("<", backslash + "u003c").replace(">", backslash + "u003e")
        self.assertNotIn("<", raw)  # sanity: fixture really is escaped, not literal

        decoded = _decode_flight_chunk(raw)

        self.assertEqual(decoded, plain)

    def test_extract_chinese_body_html_finds_dt_article_region(self):
        region = _extract_chinese_body_html(AIHOT_FIXTURE_HTML)

        self.assertIsNotNone(region)
        self.assertIn("关键要点", region)
        self.assertIn("一个德国研究联盟", region)
        # must not spill past its own </div> into the following <script> tags
        self.assertNotIn("self.__next_f", region)

    def test_extract_english_original_html_picks_the_article_chunk_not_the_decoy(self):
        english_html = _extract_english_original_html(AIHOT_FIXTURE_HTML)

        self.assertIsNotNone(english_html)
        self.assertIn("Key Points", english_html)
        self.assertIn("Soofi S", english_html)
        self.assertNotIn("70", english_html)  # the decoy chunk's content

    def test_fetch_aihot_item_content_returns_bilingual_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.crawlers.aihot_content._throttle_domain"), patch(
                "app.crawlers.aihot_content.fetch_url_text",
                return_value=AIHOT_FIXTURE_HTML,
            ) as mock_fetch:
                payload = fetch_aihot_item_content(
                    "https://aihot.virxact.com/items/cmrj6actv0651bilkm5pfz6ub",
                    cache_dir=Path(tmp),
                )

            self.assertIsNotNone(payload)
            metadata = payload["metadata"]
            self.assertIn("关键要点", metadata["original_text"] + "".join(metadata["translated_paragraphs"]))
            self.assertTrue(any("Soofi S" in p for p in metadata["original_paragraphs"]))
            self.assertTrue(any("德国研究联盟" in p for p in metadata["translated_paragraphs"]))
            self.assertEqual(metadata["translation_source_language"], "en")
            self.assertEqual(metadata["translation_target_language"], "zh")
            self.assertEqual(metadata["translation_status"], "completed")
            self.assertTrue(metadata["translation_source_hash"])
            self.assertEqual(payload["language"], "en")

            # fetch_url_text called with the identifying, non-browser UA
            self.assertEqual(mock_fetch.call_args.kwargs["user_agent"], AIHOT_USER_AGENT)

    def test_fetch_aihot_item_content_caches_across_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.crawlers.aihot_content._throttle_domain"), patch(
                "app.crawlers.aihot_content.fetch_url_text",
                return_value=AIHOT_FIXTURE_HTML,
            ) as mock_fetch:
                url = "https://aihot.virxact.com/items/cached-example"
                fetch_aihot_item_content(url, cache_dir=Path(tmp))
                fetch_aihot_item_content(url, cache_dir=Path(tmp))

            self.assertEqual(mock_fetch.call_count, 1)

    def test_fetch_aihot_item_content_is_best_effort_on_fetch_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "app.crawlers.aihot_content.fetch_url_text",
                side_effect=RuntimeError("network error"),
            ):
                payload = fetch_aihot_item_content(
                    "https://aihot.virxact.com/items/broken",
                    cache_dir=Path(tmp),
                )

            self.assertIsNone(payload)

    def test_fetch_aihot_item_content_chinese_only_sets_original_not_translation(self):
        # some AI HOT items never had an English original to begin with
        # (zh-native source, e.g. a WeChat article) or the RSC chunk simply
        # didn't match this deploy's format - either way, a lone Chinese DOM
        # block must become the *original*, not get mislabeled as a
        # "translation" of a non-existent English original
        html = AIHOT_FIXTURE_HTML.replace(
            f'<script>self.__next_f.push([1,"{_ENGLISH_HTML}"])</script>', ""
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.crawlers.aihot_content._throttle_domain"), patch(
                "app.crawlers.aihot_content.fetch_url_text", return_value=html
            ):
                payload = fetch_aihot_item_content(
                    "https://aihot.virxact.com/items/zh-only",
                    cache_dir=Path(tmp),
                )

            self.assertIsNotNone(payload)
            metadata = payload["metadata"]
            self.assertTrue(any("德国研究联盟" in p for p in metadata["original_paragraphs"]))
            self.assertNotIn("translated_paragraphs", metadata)
            self.assertNotIn("translation_status", metadata)
            self.assertEqual(payload["language"], "zh")

    def test_fetch_aihot_item_content_english_only_sets_language_en(self):
        # the mirror case: only the English RSC chunk extracted (no
        # .dt-article DOM match) - must still surface as original with
        # language=="en" so runner.py's generic translation fallback picks
        # it up, rather than silently staying language-less
        html = AIHOT_FIXTURE_HTML.replace(
            '<div class="dt-article">', '<div class="not-matched-block">'
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch("app.crawlers.aihot_content._throttle_domain"), patch(
                "app.crawlers.aihot_content.fetch_url_text", return_value=html
            ):
                payload = fetch_aihot_item_content(
                    "https://aihot.virxact.com/items/en-only",
                    cache_dir=Path(tmp),
                )

            self.assertIsNotNone(payload)
            metadata = payload["metadata"]
            self.assertTrue(any("Soofi S" in p for p in metadata["original_paragraphs"]))
            self.assertNotIn("translated_paragraphs", metadata)
            self.assertNotIn("translation_status", metadata)
            self.assertEqual(payload["language"], "en")

    def test_assign_original_and_translation_same_language_picks_longer_no_translation(self):
        # both extracted blocks resolve to the same detected language
        # (heuristic drift, or genuinely no translation pair) - must not
        # fabricate a translated_* pair out of two same-language blocks
        short_zh = extract_article_content("<p>短句一。</p>", base_url="https://x.test")
        long_zh = extract_article_content(
            "<p>" + "这是一段更长的中文正文内容用来验证长度比较逻辑。" * 5 + "</p>",
            base_url="https://x.test",
        )

        metadata, language = _assign_original_and_translation(long_zh, short_zh)

        self.assertEqual(language, "zh")
        self.assertEqual(metadata["original_paragraphs"], long_zh["original_paragraphs"])
        self.assertNotIn("translated_paragraphs", metadata)

    def test_assign_original_and_translation_no_blocks_returns_empty(self):
        metadata, language = _assign_original_and_translation(None, None)

        self.assertEqual(metadata, {})
        self.assertIsNone(language)


if __name__ == "__main__":
    unittest.main()

import io
import sys
import unittest
import urllib.error
from base64 import b64encode
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.crawlers.attentionvc import parse_attentionvc_entries
from app.crawlers.base import normalize_article
from app.crawlers.article_content import (
    CONTENT_EXTRACTION_VERSION,
    content_extraction_version_for_url,
    extract_article_content,
)
from app.crawlers.github import parse_github_trending
from app.crawlers.github_readme import (
    fetch_github_readme,
    markdown_to_original_payload,
    repo_path_from_github_url,
)
from app.crawlers.hn import HackerNewsCrawler, parse_hn_hits
from app.crawlers.huggingface_papers import parse_huggingface_papers
from app.crawlers.rss import parse_datetime, parse_rss
from app.crawlers.sitemap import main_content_region
from app.crawlers.v2ex import parse_v2ex_topics
from app.models.domain import Source


class CrawlerTests(unittest.TestCase):
    def test_normalize_article_removes_tracking_and_hashes_url_and_title(self):
        source = Source(
            id="openai_blog",
            name="OpenAI Blog",
            source_role="authority",
            tier="T1",
            type="rss",
            category="official",
            url="https://openai.com/blog/rss.xml",
            homepage="https://openai.com",
            allowed_domains=["openai.com"],
            can_be_main_source=True,
        )

        article = normalize_article(
            source=source,
            source_url="https://openai.com/blog/example?utm_source=x#comments",
            title="  New Agent Model  ",
            content="A useful AI release.",
            author="OpenAI",
            published_at=datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc),
            language="en",
            raw_score={"points": 10},
            metadata={"origin": "fixture"},
        )

        self.assertEqual(article.source_url, "https://openai.com/blog/example")
        self.assertEqual(article.title, "New Agent Model")
        self.assertEqual(len(article.url_hash), 64)
        self.assertEqual(len(article.title_hash), 64)

    def test_parse_rss_returns_normalized_articles(self):
        source = Source(
            id="fixture_rss",
            name="Fixture RSS",
            source_role="context",
            tier="T2",
            type="rss",
            category="media",
            url="https://example.com/rss.xml",
            homepage="https://example.com",
            allowed_domains=["example.com"],
            can_be_main_source=True,
        )
        xml = """<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <title>Fixture</title>
            <item>
              <title>AI system ships</title>
              <link>https://example.com/ai-system?utm_campaign=test</link>
              <description>Important model update.</description>
              <category>AI 产品</category>
              <pubDate>Wed, 01 Jul 2026 08:00:00 GMT</pubDate>
              <author>Reporter</author>
            </item>
          </channel>
        </rss>
        """

        articles = parse_rss(xml, source)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "AI system ships")
        self.assertEqual(articles[0].source_url, "https://example.com/ai-system")
        self.assertEqual(articles[0].metadata["feed_category"], "AI 产品")
        self.assertEqual(articles[0].metadata["feed_position"], 1)

    def test_aihot_rss_uses_original_url_from_description_as_source_url(self):
        source = Source(
            id="aihot_feed",
            name="AI HOT 每日精选",
            source_role="aggregator",
            tier="T3",
            type="rss",
            category="media",
            url="https://aihot.virxact.com/feed.xml",
            homepage="https://aihot.virxact.com",
            allowed_domains=["aihot.virxact.com"],
            language="zh",
            can_be_main_source=False,
            config={"original_url_from_description": True},
        )
        xml = """<?xml version="1.0"?>
        <rss version="2.0"><channel><item>
          <title><![CDATA[博科圣地如何利用前沿AI技术]]></title>
          <link>https://aihot.virxact.com/items/cmrfiocpi0035ihjlcm4qu8af</link>
          <description><![CDATA[研究摘要正文。

🔗 阅读原文：https://casp.ac/reports/ai-enabled-terrorism

via AI HOT · https://aihot.virxact.com/items/cmrfiocpi0035ihjlcm4qu8af]]></description>
          <category>论文</category>
          <pubDate>Fri, 10 Jul 2026 22:07:19 GMT</pubDate>
        </item></channel></rss>
        """

        articles = parse_rss(xml, source)

        self.assertEqual(
            articles[0].source_url,
            "https://casp.ac/reports/ai-enabled-terrorism",
        )

    def test_aihot_rss_falls_back_to_item_link_without_original_url(self):
        source = Source(
            id="aihot_feed",
            name="AI HOT 每日精选",
            source_role="aggregator",
            tier="T3",
            type="rss",
            category="media",
            url="https://aihot.virxact.com/feed.xml",
            homepage="https://aihot.virxact.com",
            allowed_domains=["aihot.virxact.com"],
            config={"original_url_from_description": True},
        )
        xml = """<rss><channel><item>
          <title>无原文链接的条目</title>
          <link>https://aihot.virxact.com/items/fallback</link>
          <description>只有摘要，没有阅读原文。</description>
        </item></channel></rss>"""

        articles = parse_rss(xml, source)

        self.assertEqual(
            articles[0].source_url,
            "https://aihot.virxact.com/items/fallback",
        )

    def test_aihot_rss_extracts_summary_zh_from_description(self):
        # AI HOT's own description IS an AI-written summary - use it
        # verbatim as summary_zh instead of re-summarizing ourselves
        source = Source(
            id="aihot_feed",
            name="AI HOT 每日精选",
            source_role="aggregator",
            tier="T3",
            type="rss",
            category="media",
            url="https://aihot.virxact.com/feed.xml",
            homepage="https://aihot.virxact.com",
            allowed_domains=["aihot.virxact.com"],
            language="zh",
            can_be_main_source=False,
            config={"original_url_from_description": True},
        )
        xml = """<?xml version="1.0"?>
        <rss version="2.0"><channel><item>
          <title><![CDATA[德国AI协会发布开源模型Soofi S]]></title>
          <link>https://aihot.virxact.com/items/cmrj6actv0651bilkm5pfz6ub</link>
          <description><![CDATA[德国AI协会协调的研究联盟发布开源大语言模型Soofi S 30B-A3B。

🔗 阅读原文：https://the-decoder.com/german-ai-consortium

via AI HOT · https://aihot.virxact.com/items/cmrj6actv0651bilkm5pfz6ub]]></description>
          <category>AI 模型</category>
          <pubDate>Mon, 13 Jul 2026 11:41:01 GMT</pubDate>
        </item></channel></rss>
        """

        articles = parse_rss(xml, source)

        self.assertEqual(
            articles[0].metadata["aihot_summary_zh"],
            "德国AI协会协调的研究联盟发布开源大语言模型Soofi S 30B-A3B。",
        )

    def test_aihot_rss_content_excludes_read_original_marker_and_url(self):
        # the "阅读原文：<url>" / "via AI HOT · <permalink>" tail is our own
        # generated link-out boilerplate, not article body - it must not leak
        # into article.content or original_paragraphs (it used to, since only
        # aihot_summary_zh was cleaned, not the body fed to
        # extract_article_content)
        source = Source(
            id="aihot_feed",
            name="AI HOT 每日精选",
            source_role="aggregator",
            tier="T3",
            type="rss",
            category="media",
            url="https://aihot.virxact.com/feed.xml",
            homepage="https://aihot.virxact.com",
            allowed_domains=["aihot.virxact.com"],
            language="zh",
            can_be_main_source=False,
            config={"original_url_from_description": True},
        )
        xml = """<?xml version="1.0"?>
        <rss version="2.0"><channel><item>
          <title><![CDATA[德国AI协会发布开源模型Soofi S]]></title>
          <link>https://aihot.virxact.com/items/cmrj6actv0651bilkm5pfz6ub</link>
          <description><![CDATA[德国AI协会协调的研究联盟发布开源大语言模型Soofi S 30B-A3B。

🔗 阅读原文：https://the-decoder.com/german-ai-consortium

via AI HOT · https://aihot.virxact.com/items/cmrj6actv0651bilkm5pfz6ub]]></description>
          <category>AI 模型</category>
          <pubDate>Mon, 13 Jul 2026 11:41:01 GMT</pubDate>
        </item></channel></rss>
        """

        articles = parse_rss(xml, source)

        self.assertNotIn("阅读原文", articles[0].content)
        self.assertNotIn("the-decoder.com", articles[0].content)
        self.assertNotIn("via AI HOT", articles[0].content)
        for paragraph in articles[0].metadata["original_paragraphs"]:
            self.assertNotIn("阅读原文", paragraph)
            self.assertNotIn("the-decoder.com", paragraph)

    def test_aihot_rss_captures_permalink_only_when_use_aihot_item_page(self):
        xml = """<?xml version="1.0"?>
        <rss version="2.0"><channel><item>
          <title><![CDATA[条目标题]]></title>
          <link>https://aihot.virxact.com/items/abc123</link>
          <description><![CDATA[摘要正文。

🔗 阅读原文：https://example.com/original

via AI HOT · https://aihot.virxact.com/items/abc123]]></description>
          <pubDate>Mon, 13 Jul 2026 11:41:01 GMT</pubDate>
        </item></channel></rss>
        """

        def source_with(config):
            return Source(
                id="aihot_feed",
                name="AI HOT 每日精选",
                source_role="aggregator",
                tier="T3",
                type="rss",
                category="media",
                url="https://aihot.virxact.com/feed.xml",
                homepage="https://aihot.virxact.com",
                allowed_domains=["aihot.virxact.com"],
                language="zh",
                can_be_main_source=False,
                config=config,
            )

        with_flag = parse_rss(xml, source_with({"use_aihot_item_page": True}))
        self.assertEqual(
            with_flag[0].metadata["aihot_permalink"],
            "https://aihot.virxact.com/items/abc123",
        )
        # source_url itself is unaffected - still the third-party original
        self.assertEqual(with_flag[0].source_url, "https://example.com/original")

        without_flag = parse_rss(xml, source_with({}))
        self.assertNotIn("aihot_permalink", without_flag[0].metadata)

    def test_extract_article_content_preserves_blocks_and_image_urls(self):
        html = """
        <article>
          <p>第一段 AI 正文。</p>
          <p><img src="/images/demo.jpg" alt="模型界面截图"></p>
          <p>第二段继续说明。</p>
        </article>
        """

        content = extract_article_content(html, base_url="https://www.ithome.com/0/973/803.htm")

        self.assertEqual(content["original_paragraphs"], ["第一段 AI 正文。", "第二段继续说明。"])
        self.assertEqual(
            content["original_blocks"],
            [
                {"type": "paragraph", "text": "第一段 AI 正文。"},
                {
                    "type": "image",
                    "url": "https://www.ithome.com/images/demo.jpg",
                    "alt": "模型界面截图",
                    "caption": "",
                },
                {"type": "paragraph", "text": "第二段继续说明。"},
            ],
        )
        self.assertEqual(content["original_images"][0]["url"], "https://www.ithome.com/images/demo.jpg")

    def test_substack_srcset_and_x_embed_are_preserved(self):
        image_url = (
            "https://substackcdn.com/image/fetch/$s_!abc!,w_1456,c_limit,"
            "f_webp,q_auto:good,fl_progressive:steep/"
            "https%3A%2F%2Fsubstack-post-media.s3.amazonaws.com%2Fimage.png"
        )
        html = f"""
        <article>
          <p>Before media.</p>
          <figure><picture>
            <source srcset="
              https://substackcdn.com/image/fetch/$s_!abc!,w_424,c_limit,f_webp,q_auto:good,fl_progressive:steep/https%3A%2F%2Fsubstack-post-media.s3.amazonaws.com%2Fimage.png 424w,
              {image_url} 1456w">
            <img src="{image_url}" width="1456" height="863">
          </picture></figure>
          <div class="tweet twitter-embed" data-attrs='{{"url":"https://twitter.com/Kimi_Moonshot/status/2077521842080817296?s=12","username":"Kimi_Moonshot","name":"Kimi.ai","profile_image_url":"https://pbs.substack.com/profile.jpg","date":"2026-07-15T22:33:00.000Z","video_url":"https://video.twimg.com/media/demo.mp4","photos":[{{"img_url":"https://pbs.substack.com/poster.jpg"}}],"reply_count":634,"retweet_count":931,"like_count":11466,"impression_count":1888250}}'>
            <video src="https://video.twimg.com/media/demo.mp4"></video>
          </div>
          <p>After media.</p>
        </article>
        """

        content = extract_article_content(
            html,
            base_url="https://www.latent.space/p/example",
        )

        self.assertEqual(content["original_images"][0]["url"], image_url)
        self.assertNotIn("www.latent.space/p/fl_progressive", str(content))
        social_blocks = [
            block
            for block in content["original_blocks"]
            if block["type"] == "social_embed"
        ]
        self.assertEqual(len(social_blocks), 1)
        self.assertEqual(
            social_blocks[0]["url"],
            "https://x.com/Kimi_Moonshot/status/2077521842080817296",
        )
        self.assertEqual(social_blocks[0]["author_name"], "Kimi.ai")
        self.assertEqual(social_blocks[0]["video_mime_type"], "video/mp4")
        self.assertEqual(social_blocks[0]["view_count"], 1888250)
        self.assertFalse(
            any(block["type"] == "video" for block in content["original_blocks"])
        )
        self.assertEqual(
            content_extraction_version_for_url(
                "https://www.latent.space/p/example"
            ),
            4,
        )

    def test_latent_space_drops_discussion_and_free_trial_tails(self):
        cases = (
            (
                "Discussion about this episode",
                "<img src='https://cdn.example/discussion-avatar.jpg'>",
            ),
            (
                "Keep reading with a 7-day free trial",
                "<p>Subscribe to keep reading this post.</p>",
            ),
        )
        for boundary, tail in cases:
            with self.subTest(boundary=boundary):
                html = f"""
                <article>
                  <p>Useful article body.</p>
                  <h4>{boundary}</h4>
                  {tail}
                </article>
                """
                content = extract_article_content(
                    html,
                    base_url="https://www.latent.space/p/example",
                )

                self.assertEqual(
                    content["original_blocks"],
                    [{"type": "paragraph", "text": "Useful article body."}],
                )
                self.assertEqual(content["original_images"], [])
                self.assertNotIn(boundary, content["original_text"])

        other_source = extract_article_content(
            """
            <article>
              <p>Useful article body.</p>
              <h4>Discussion about this episode</h4>
              <p>A legitimate section on another site.</p>
            </article>
            """,
            base_url="https://example.com/post",
        )
        self.assertIn("Discussion about this episode", other_source["original_text"])

    def test_extract_article_content_skips_avatar_cdn_images(self):
        # 真实案例：HuggingFace 博客页把"点赞用户头像"小组件跟正文放在
        # 同一个 <main> 容器里，之前会把这些头像当成正文插图存下来。
        html = """
        <article>
          <p>第一段正文。</p>
          <img src="https://cdn-avatars.huggingface.co/v1/production/uploads/abc.jpeg" alt="sayakpaul">
          <img src="https://huggingface.co/avatars/212fbe902f134e1c516976f33c2a35a7.svg" alt="anon">
          <p><img src="https://huggingface.co/datasets/huggingface/documentation-images/resolve/main/fig1.png"></p>
          <p>第二段正文。</p>
        </article>
        """

        content = extract_article_content(html, base_url="https://huggingface.co/blog/example")

        image_urls = [img["url"] for img in content["original_images"]]
        self.assertNotIn(
            "https://cdn-avatars.huggingface.co/v1/production/uploads/abc.jpeg", image_urls
        )
        self.assertNotIn(
            "https://huggingface.co/avatars/212fbe902f134e1c516976f33c2a35a7.svg", image_urls
        )
        self.assertIn(
            "https://huggingface.co/datasets/huggingface/documentation-images/resolve/main/fig1.png",
            image_urls,
        )
        self.assertEqual(content["original_paragraphs"], ["第一段正文。", "第二段正文。"])

    def test_extract_article_content_drops_leading_block_that_duplicates_title(self):
        # 真实案例（the-decoder.com）：正文区域是整个 <article>，其中包含
        # 独立渲染的 <h1> 标题——提取时把它当成了第一段正文，导致标题在
        # 详情页重复出现一次。跨源实测发现 40 篇文章受此影响。
        html = """
        <article>
          <h1>OpenAI admits it "didn't get everything quite right"</h1>
          <p>Real body text starts here and continues for a while.</p>
        </article>
        """

        content = extract_article_content(
            html,
            base_url="https://the-decoder.com/x",
            title='OpenAI admits it "didn\'t get everything quite right"',
        )

        self.assertEqual(
            content["original_paragraphs"],
            ["Real body text starts here and continues for a while."],
        )

    def test_extract_article_content_keeps_leading_block_when_no_title_given(self):
        # 向后兼容：不传 title 时行为不变（RSS 摘要等场景本就没有标题可比对）
        html = "<article><p>Same as heading text</p><p>More body.</p></article>"

        content = extract_article_content(html, base_url="https://example.com/x")

        self.assertEqual(content["original_paragraphs"], ["Same as heading text", "More body."])

    def test_extract_article_content_skips_byline_avatar_by_filename_pattern(self):
        # 真实案例（the-decoder.com）：作者头像走站内相对路径
        # /resources/images/avatar_matthias_bastian.jpg，不在任何已知头像
        # CDN host 列表里，之前会被当成正文插图存下来
        html = """
        <article>
          <h1>Some headline</h1>
          <div class="byline">
            <img src="/resources/images/avatar_matthias_bastian.jpg" alt="Matthias Bastian">
          </div>
          <img src="https://the-decoder.com/wp-content/uploads/2026/07/hero.png" alt="Image description">
          <p>Real body paragraph with enough length to pass extraction thresholds easily.</p>
        </article>
        """

        content = extract_article_content(html, base_url="https://the-decoder.com/x")

        image_urls = [img["url"] for img in content["original_images"]]
        self.assertNotIn("https://the-decoder.com/resources/images/avatar_matthias_bastian.jpg", image_urls)
        self.assertIn("https://the-decoder.com/wp-content/uploads/2026/07/hero.png", image_urls)

    def test_extract_article_content_preserves_inline_links_and_bold(self):
        html = (
            "<article>"
            '<p>Read the <a href="https://example.com/paper">full paper</a> for '
            "<strong>key results</strong> and <em>analysis</em> of <code>gpt-5</code>.</p>"
            "<p>Plain paragraph without markup.</p>"
            '<p>Ignore <a href="javascript:alert(1)">bad link</a> schemes '
            'and <span onclick="x()">spans</span>.</p>'
            "</article>"
        )

        result = extract_article_content(html, base_url="https://example.com/post")

        rich = result["original_blocks"][0]
        self.assertEqual(rich["type"], "paragraph")
        self.assertIn("full paper", rich["text"])  # plain text always present
        self.assertIn('<a href="https://example.com/paper">full paper</a>', rich["html"])
        self.assertIn("<strong>key results</strong>", rich["html"])
        self.assertIn("<em>analysis</em>", rich["html"])
        self.assertIn("<code>gpt-5</code>", rich["html"])

        plain = result["original_blocks"][1]
        self.assertNotIn("html", plain)  # no markup -> no html payload

        unsafe = result["original_blocks"][2]
        html_payload = unsafe.get("html", "")
        self.assertNotIn("javascript:", html_payload)
        self.assertNotIn("onclick", html_payload)
        self.assertNotIn("<span", html_payload)

    def test_extract_article_content_produces_heading_blocks_with_levels(self):
        html = (
            "<article>"
            "<h1>主标题</h1>"
            "<p>第一段正文。</p>"
            "<h2>小节标题</h2>"
            "<p>第二段正文。</p>"
            "</article>"
        )

        content = extract_article_content(html, base_url="https://example.com/x")

        self.assertEqual(
            content["original_blocks"],
            [
                {"type": "heading", "level": 1, "text": "主标题"},
                {"type": "paragraph", "text": "第一段正文。"},
                {"type": "heading", "level": 2, "text": "小节标题"},
                {"type": "paragraph", "text": "第二段正文。"},
            ],
        )
        # heading text still flows into the flat paragraph/text fallback lists
        self.assertIn("主标题", content["original_paragraphs"])
        self.assertIn("主标题", content["original_text"])

    def test_extract_article_content_preserves_valid_inline_color(self):
        html = (
            "<article>"
            '<p>正常文字 <span style="color: #ff0000">红色文字</span> 结尾。</p>'
            '<p>旧式标签 <font color="blue">蓝色文字</font> 结尾。</p>'
            "</article>"
        )

        content = extract_article_content(html, base_url="https://example.com/x")

        first, second = content["original_blocks"]
        self.assertIn('<span style="color: #ff0000">红色文字</span>', first["html"])
        self.assertIn('<span style="color: blue">蓝色文字</span>', second["html"])
        self.assertIn("红色文字", first["text"])

    def test_extract_article_content_rejects_unsafe_inline_style_values(self):
        html = (
            "<article>"
            '<p>危险样式 <span style="color: url(javascript:alert(1))">文字</span> 结尾。</p>'
            "</article>"
        )

        content = extract_article_content(html, base_url="https://example.com/x")

        block = content["original_blocks"][0]
        self.assertNotIn("html", block)
        self.assertIn("文字", block["text"])
        self.assertIn("危险样式", block["text"])

    def test_extract_article_content_strips_trailing_boilerplate(self):
        # 真实案例（36氪）：正文容器把版权声明/转载说明/图片来源和"寻求
        # 报道"CTA 跟正文放在同一个容器里，之前会原样展示出来。
        html = """
        <article>
          <p>36氪获悉，某公司披露业绩预告，预计净利润同比增长显著。</p>
          <p>本文由「卜算籽」原创出品， 转载或内容合作请点击 <a href="https://x.com/repost">转载说明</a> ；违规转载必究。</p>
          <p><a href="https://x.com/tip">寻求报道</a></p>
          <p>本文图片来自：AI生成</p>
        </article>
        """

        content = extract_article_content(html, base_url="https://36kr.com/p/x")

        self.assertEqual(
            content["original_paragraphs"],
            ["36氪获悉，某公司披露业绩预告，预计净利润同比增长显著。"],
        )
        self.assertEqual(len(content["original_blocks"]), 1)

    def test_extract_article_content_strips_qbitai_footer_past_trending_widget_and_qrcode(self):
        # 真实案例（量子位）：正文容器末尾是"热门文章"推荐列表（标题+配图，
        # 不含任何版权关键词，不应被误删），再往后才是真正的版权页脚
        # （关于X/加入我们/寻求报道/商务合作/扫码关注X + 二维码图片）。
        # 图片本身没有关键词可匹配，之前会直接把扫描打断在图片上。
        html = """
        <article>
          <p>正文第一段，介绍产品发布的具体细节。</p>
          <p>正文第二段，继续说明技术要点。</p>
          <h5>热门文章</h5>
          <h5>刚刚，OpenAI首席未来学家离职！曾被马斯克骂蠢驴</h5>
          <p><img src="https://i.qbitai.com/thumb1.png"></p>
          <h5>50FPS、成本打掉70%，魔芯MoWorld把世界模型带进产业时代</h5>
          <p><img src="https://i.qbitai.com/thumb2.png"></p>
          <p>关于量子位</p>
          <p>加入我们</p>
          <p><a href="https://www.qbitai.com/?page_id=103">寻求报道</a></p>
          <p>商务合作</p>
          <p>扫码关注量子位</p>
          <p><img src="https://www.qbitai.com/wp-content/uploads/2019/01/qrcode_QbitAI_1.jpg"></p>
        </article>
        """

        content = extract_article_content(html, base_url="https://www.qbitai.com/x")

        # the trending-article widget (heading + thumbnail pairs) is a
        # separate, harder problem - out of scope here, so it's expected to
        # still survive; only the copyright/about footer + its qrcode go
        block_texts_by_type = [(b["type"], b.get("text")) for b in content["original_blocks"]]
        self.assertEqual(
            block_texts_by_type,
            [
                ("paragraph", "正文第一段，介绍产品发布的具体细节。"),
                ("paragraph", "正文第二段，继续说明技术要点。"),
                ("heading", "热门文章"),
                ("heading", "刚刚，OpenAI首席未来学家离职！曾被马斯克骂蠢驴"),
                ("image", None),
                ("heading", "50FPS、成本打掉70%，魔芯MoWorld把世界模型带进产业时代"),
                ("image", None),
            ],
        )
        self.assertNotIn(
            "https://www.qbitai.com/wp-content/uploads/2019/01/qrcode_QbitAI_1.jpg",
            [img["url"] for img in content["original_images"]],
        )

    def test_extract_article_content_keeps_legitimate_paragraph_mentioning_copyright(self):
        # 反例：正文中间合法提到"版权"不应被误删（只扫描末尾几段）
        html = """
        <article>
          <p>某公司陷入版权纠纷，法院一审判决其败诉并需赔偿。</p>
          <p>该案件持续关注中，后续进展仍需观察行业反应。</p>
        </article>
        """

        content = extract_article_content(html, base_url="https://example.com/x")

        self.assertEqual(
            content["original_paragraphs"],
            [
                "某公司陷入版权纠纷，法院一审判决其败诉并需赔偿。",
                "该案件持续关注中，后续进展仍需观察行业反应。",
            ],
        )

    def test_extract_article_content_removes_aws_ml_about_the_authors_line_only(self):
        html = """
        <article>
          <h2>Related resources</h2>
          <p>Amazon Bedrock documentation.</p>
          <h2>About the authors</h2>
        </article>
        """

        content = extract_article_content(
            html,
            base_url="https://aws.amazon.com/blogs/machine-learning/example-post/",
        )

        self.assertEqual(
            content["original_paragraphs"],
            ["Related resources", "Amazon Bedrock documentation."],
        )
        self.assertEqual(
            [(block["type"], block.get("text")) for block in content["original_blocks"]],
            [
                ("heading", "Related resources"),
                ("paragraph", "Amazon Bedrock documentation."),
            ],
        )

    def test_extract_article_content_keeps_same_line_for_non_aws_sources(self):
        content = extract_article_content(
            "<article><h2>About the authors</h2></article>",
            base_url="https://example.com/post",
        )

        self.assertEqual(content["original_paragraphs"], ["About the authors"])

    def test_extract_article_content_removes_nvidia_trailing_categories_and_tags(self):
        html = """
        <article>
          <p>Builders are adding Nemotron to their AI systems.</p>
          <p>Learn more about NVIDIA Nemotron open models.</p>
          <ul>
            <li>Categories:</li>
            <li><a href="/blog/category/generative-ai/">AI</a></li>
          </ul>
          <ul>
            <li>Tags:</li>
            <li><a href="/blog/tag/agentic-ai/">Agentic AI</a></li>
            <li><a href="/blog/tag/nemotron/">Nemotron</a></li>
          </ul>
        </article>
        """

        content = extract_article_content(
            html,
            base_url="https://blogs.nvidia.com/blog/nemotron-open-models",
        )

        self.assertEqual(
            content["original_paragraphs"],
            [
                "Builders are adding Nemotron to their AI systems.",
                "Learn more about NVIDIA Nemotron open models.",
            ],
        )
        self.assertEqual(
            [block["type"] for block in content["original_blocks"]],
            ["paragraph", "paragraph"],
        )
        self.assertEqual(
            content_extraction_version_for_url("https://blogs.nvidia.com/blog/example"),
            3,
        )
        self.assertEqual(
            content_extraction_version_for_url("https://example.com/post"),
            CONTENT_EXTRACTION_VERSION,
        )

    def test_extract_article_content_keeps_taxonomy_lists_for_non_nvidia_sources(self):
        content = extract_article_content(
            "<article><p>Body.</p><ul><li>Categories:</li><li>AI</li></ul></article>",
            base_url="https://example.com/post",
        )

        self.assertEqual(content["original_paragraphs"], ["Body.", "Categories:", "AI"])

    def test_extract_article_content_removes_anthropic_related_content_section(self):
        html = """
        <article>
          <p>The final paragraph of the actual announcement.</p>
          <h2>Related content</h2>
          <h3>Introducing Claude for Teachers</h3>
          <h3>Inviting hard questions</h3>
          <p>We are asking the public for their hardest questions about AI.</p>
        </article>
        """

        content = extract_article_content(
            html,
            base_url="https://www.anthropic.com/news/canadian-ai-research",
        )

        self.assertEqual(
            content["original_paragraphs"],
            ["The final paragraph of the actual announcement."],
        )
        self.assertEqual(
            content_extraction_version_for_url(
                "https://www.anthropic.com/news/canadian-ai-research"
            ),
            3,
        )

    def test_extract_article_content_keeps_related_content_for_other_sources(self):
        content = extract_article_content(
            "<article><p>Body.</p><h2>Related content</h2></article>",
            base_url="https://example.com/post",
        )

        self.assertEqual(content["original_paragraphs"], ["Body.", "Related content"])

    def test_extract_article_content_starts_google_blog_body_after_audio_fallback(self):
        html = """
        <article>
          <h1>Expanding Managed Agents in Gemini API</h1>
          <p>Jul 07, 2026</p>
          <p>We are adding support for new capabilities.</p>
          <img src="https://storage.googleapis.com/audio-presenter.webp">
          <img src="https://storage.googleapis.com/audio-cover.webp">
          <p>Your browser does not support the audio element.</p>
          <p>Today we are announcing new capabilities for Managed Agents.</p>
          <img src="https://storage.googleapis.com/body-diagram.webp">
        </article>
        """

        content = extract_article_content(
            html,
            base_url="https://blog.google/innovation-and-ai/example",
        )

        self.assertEqual(
            content["original_paragraphs"],
            ["Today we are announcing new capabilities for Managed Agents."],
        )
        self.assertEqual(
            [image["url"] for image in content["original_images"]],
            ["https://storage.googleapis.com/body-diagram.webp"],
        )
        self.assertEqual(
            [block["type"] for block in content["original_blocks"]],
            ["paragraph", "image"],
        )
        self.assertEqual(
            content_extraction_version_for_url(
                "https://blog.google/innovation-and-ai/example"
            ),
            4,
        )

    def test_extract_article_content_keeps_audio_fallback_for_other_sources(self):
        content = extract_article_content(
            "<article><p>Intro.</p><p>Your browser does not support the audio element.</p>"
            "<p>Body.</p></article>",
            base_url="https://example.com/post",
        )

        self.assertEqual(
            content["original_paragraphs"],
            ["Intro.", "Your browser does not support the audio element.", "Body."],
        )

    def test_extract_article_content_reads_google_custom_code_blocks(self):
        html = """
        <article>
          <p>Before the example.</p>
          <uni-code-block
            code="import { GoogleGenAI } from &quot;@google/genai&quot;;&#10;const client = new GoogleGenAI({});"
            lang="ts"></uni-code-block>
          <p>After the example.</p>
        </article>
        """

        content = extract_article_content(
            html,
            base_url="https://blog.google/innovation-and-ai/example",
        )

        self.assertEqual(
            [block["type"] for block in content["original_blocks"]],
            ["paragraph", "code", "paragraph"],
        )
        code = content["original_blocks"][1]
        self.assertEqual(code["language"], "ts")
        self.assertEqual(
            code["text"],
            'import { GoogleGenAI } from "@google/genai";\nconst client = new GoogleGenAI({});',
        )
        self.assertEqual(
            content_extraction_version_for_url(
                "https://blog.google/innovation-and-ai/example"
            ),
            4,
        )

    def test_extract_article_content_ignores_google_custom_code_tag_on_other_sources(self):
        content = extract_article_content(
            '<article><p>Before.</p><uni-code-block code="secret()" lang="js">'
            "</uni-code-block><p>After.</p></article>",
            base_url="https://example.com/post",
        )

        self.assertEqual(content["original_paragraphs"], ["Before.", "After."])

    def test_parse_rss_preserves_original_text_blocks_and_images(self):
        source = Source(
            id="ithome",
            name="IT之家（RSS）",
            source_role="context",
            tier="T2",
            type="rss",
            category="media",
            url="https://www.ithome.com/rss/",
            homepage="https://www.ithome.com",
            allowed_domains=["ithome.com", "www.ithome.com"],
            language="zh",
            can_be_main_source=True,
            config={"extract_original_content": True},
        )
        xml = """<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>AI 应用更新</title>
              <link>https://www.ithome.com/0/973/803.htm</link>
              <description>&lt;p&gt;IT之家 7 月 7 日消息，AI 应用发布更新。&lt;/p&gt;&lt;p&gt;&lt;img src="https://img.ithome.com/news/demo.jpg" alt="更新截图"&gt;&lt;/p&gt;&lt;p&gt;新版本增加本地模型能力。&lt;/p&gt;</description>
              <pubDate>Tue, 07 Jul 2026 15:01:52 GMT</pubDate>
            </item>
          </channel>
        </rss>
        """

        articles = parse_rss(xml, source)

        self.assertEqual(len(articles), 1)
        self.assertEqual(
            articles[0].metadata["original_paragraphs"],
            ["IT之家 7 月 7 日消息，AI 应用发布更新。", "新版本增加本地模型能力。"],
        )
        self.assertEqual(
            articles[0].metadata["original_images"],
            [
                {
                    "url": "https://img.ithome.com/news/demo.jpg",
                    "alt": "更新截图",
                    "caption": "",
                }
            ],
        )
        self.assertEqual(articles[0].metadata["original_blocks"][1]["type"], "image")

    def test_parse_datetime_reinterprets_mislabeled_gmt_under_assume_tz(self):
        # InfoQ 中文 labels pubDate "GMT" but the wall-clock numbers are
        # actually Beijing time (confirmed against the real timestamp
        # embedded in the article page) - assume_tz must discard the
        # declared "GMT" and reinterpret the same numbers as +08:00
        without_override = parse_datetime("Mon, 13 Jul 2026 12:07:33 GMT")
        with_override = parse_datetime(
            "Mon, 13 Jul 2026 12:07:33 GMT", assume_tz="+08:00"
        )

        self.assertEqual(without_override, datetime(2026, 7, 13, 12, 7, 33, tzinfo=timezone.utc))
        self.assertEqual(with_override, datetime(2026, 7, 13, 4, 7, 33, tzinfo=timezone.utc))

    def test_parse_datetime_accepts_36kr_compact_offset_with_extra_spaces(self):
        parsed = parse_datetime("2026-07-15 11:05:44  +0800")

        self.assertEqual(parsed, datetime(2026, 7, 15, 3, 5, 44, tzinfo=timezone.utc))

    def test_parse_rss_marks_valid_36kr_pubdate_for_future_correction(self):
        source = Source(
            id="kr36",
            name="36氪",
            source_role="context",
            tier="T3",
            type="rss",
            category="media",
            url="https://36kr.com/feed",
            homepage="https://36kr.com",
            allowed_domains=["36kr.com"],
            language="zh",
            can_be_main_source=True,
        )
        xml = """<?xml version="1.0"?>
        <rss version="2.0"><channel><item>
          <title>长鑫科技注册资本10年增超6000倍</title>
          <link>https://36kr.com/newsflashes/3896306415568771?f=rss</link>
          <pubDate>2026-07-15 11:05:44  +0800</pubDate>
          <description>36氪获悉，长鑫科技IPO发行价敲定。</description>
        </item></channel></rss>
        """

        article = parse_rss(xml, source)[0]

        self.assertEqual(article.published_at, datetime(2026, 7, 15, 3, 5, 44, tzinfo=timezone.utc))
        self.assertFalse(article.metadata["rss_pubdate_missing"])
        self.assertEqual(article.metadata["rss_pubdate_raw"], "2026-07-15 11:05:44 +0800")

    def test_parse_rss_applies_pubdate_assume_tz_from_source_config(self):
        source = Source(
            id="infoq_cn",
            name="InfoQ 中文",
            source_role="context",
            tier="T2",
            type="rss",
            category="media",
            url="https://www.infoq.cn/feed",
            homepage="https://www.infoq.cn",
            allowed_domains=["infoq.cn"],
            language="zh",
            can_be_main_source=True,
            config={"pubdate_assume_tz": "+08:00"},
        )
        xml = """<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>红帽发布 AI 平台 3.4</title>
              <link>https://www.infoq.cn/article/aIP7uI00KLecpDYZBKXl</link>
              <description>&lt;p&gt;正文。&lt;/p&gt;</description>
              <pubDate>Mon, 13 Jul 2026 12:07:33 GMT</pubDate>
            </item>
          </channel>
        </rss>
        """

        articles = parse_rss(xml, source)

        self.assertEqual(
            articles[0].published_at, datetime(2026, 7, 13, 4, 7, 33, tzinfo=timezone.utc)
        )

    def test_parse_atom_handles_iso_dates_nested_author_and_href_links(self):
        source = Source(
            id="arxiv_ai",
            name="arXiv AI",
            source_role="authority",
            tier="T1_5",
            type="arxiv",
            category="research",
            url="https://export.arxiv.org/api/query",
            homepage="https://arxiv.org",
            allowed_domains=["arxiv.org"],
            can_be_main_source=True,
        )
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <id>http://arxiv.org/abs/2607.00001v1</id>
            <updated>2026-07-01T08:00:00Z</updated>
            <published>2026-07-01T07:30:00Z</published>
            <title>Agentic AI Benchmark</title>
            <summary>We introduce a benchmark for AI agents.</summary>
            <author><name>Researcher One</name></author>
            <link href="http://arxiv.org/abs/2607.00001v1" rel="alternate" type="text/html"/>
          </entry>
        </feed>
        """

        articles = parse_rss(xml, source)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].source_url, "http://arxiv.org/abs/2607.00001v1")
        self.assertEqual(articles[0].author, "Researcher One")
        self.assertEqual(
            articles[0].published_at,
            datetime(2026, 7, 1, 7, 30, tzinfo=timezone.utc),
        )

    def test_parse_atom_prefers_alternate_reddit_link(self):
        source = Source(
            id="reddit_localllama",
            name="Reddit r/LocalLLaMA",
            source_role="signal",
            tier="T2",
            type="rss",
            category="community",
            url="https://www.reddit.com/r/LocalLLaMA/.rss",
            homepage="https://www.reddit.com/r/LocalLLaMA/",
            allowed_domains=["reddit.com"],
            can_be_main_source=True,
        )
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>New local LLM release</title>
            <updated>2026-07-01T09:00:00+00:00</updated>
            <author><name>/u/modelbuilder</name></author>
            <link rel="replies" href="https://www.reddit.com/r/LocalLLaMA/comments/x/.rss"/>
            <link rel="alternate" href="https://www.reddit.com/r/LocalLLaMA/comments/x/new_local_llm_release/"/>
            <content type="html">&lt;p&gt;Release notes&lt;/p&gt;</content>
          </entry>
        </feed>
        """

        articles = parse_rss(xml, source)

        self.assertEqual(len(articles), 1)
        self.assertEqual(
            articles[0].source_url,
            "https://www.reddit.com/r/LocalLLaMA/comments/x/new_local_llm_release",
        )
        self.assertEqual(articles[0].author, "/u/modelbuilder")

    def test_parse_github_trending_ignores_navigation_paths(self):
        source = Source(
            id="github_trending_ai",
            name="GitHub Trending AI",
            source_role="signal",
            tier="T2",
            type="github",
            category="community",
            url="https://github.com/trending?since=daily",
            homepage="https://github.com/trending",
            allowed_domains=["github.com"],
            affects_heat_score=True,
            can_be_main_source=True,
            config={"query_terms": ["ai", "llm", "agent", "machine-learning"]},
        )
        html = """
        <a href="/trending/developers">Developers</a>
        <a href="/topics/ai">AI topic</a>
        <article class="Box-row">
          <h2><a href="/openai/agent-kit">openai / agent-kit</a></h2>
          <p>Tools for AI agents.</p>
        </article>
        <article class="Box-row">
          <h2><a href="/encode/httpx">encode / httpx</a></h2>
          <p>HTTP client.</p>
        </article>
        <article class="Box-row">
          <h2><a href="/huggingface/llm-course">huggingface / llm-course</a></h2>
          <p>LLM learning materials.</p>
        </article>
        """

        articles = parse_github_trending(html, source, limit=10)

        self.assertEqual([article.metadata["repo"] for article in articles], [
            "openai/agent-kit",
            "huggingface/llm-course",
        ])
        self.assertNotIn("GitHub Trending: trending / developers", [article.title for article in articles])

    def test_github_readme_helper_parses_repo_and_markdown_blocks(self):
        self.assertEqual(
            repo_path_from_github_url("https://github.com/MadsLorentzen/ai-job-search"),
            "MadsLorentzen/ai-job-search",
        )
        markdown = """
        <p align="center">
          <img src="assets/demo.png" alt="Demo">
        </p>

        # Agent Skills

        Production-grade skills for [AI agents](https://example.com).

        ```bash
        ignored code block
        ```

        ## Setup

        Run the installer.
        """

        payload = markdown_to_original_payload(
            markdown,
            repo_path="openai/agent-kit",
            download_url="https://raw.githubusercontent.com/openai/agent-kit/main/README.md",
        )

        self.assertEqual(
            payload["original_paragraphs"],
            ["Agent Skills", "Production-grade skills for AI agents.", "Setup", "Run the installer."],
        )
        self.assertEqual(payload["original_blocks"][0]["type"], "image")
        self.assertEqual(
            payload["original_blocks"][0]["url"],
            "https://raw.githubusercontent.com/openai/agent-kit/main/assets/demo.png",
        )
        self.assertEqual(payload["original_blocks"][1]["text"], "Agent Skills")

    def test_fetch_github_readme_decodes_api_payload_and_handles_failures(self):
        readme = (
            "# Agent Skills\n\n"
            "![Demo](assets/demo.png)\n\n"
            "Production-grade skills for [AI agents](docs/agents.md)."
        )
        api_payload = {
            "content": b64encode(readme.encode("utf-8")).decode("ascii"),
            "encoding": "base64",
            "download_url": "https://raw.githubusercontent.com/openai/agent-kit/main/README.md",
            "html_url": "https://github.com/openai/agent-kit/blob/main/README.md",
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return __import__("json").dumps(api_payload).encode("utf-8")

        with patch("urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            payload = fetch_github_readme("openai/agent-kit", github_token="test-token")

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.github.com/repos/openai/agent-kit/readme")
        self.assertIn("Authorization", request.headers)
        self.assertEqual(payload["readme_status"], "ok")
        self.assertEqual(payload["readme_url"], "https://raw.githubusercontent.com/openai/agent-kit/main/README.md")
        self.assertEqual(payload["original_paragraphs"], ["Agent Skills", "Production-grade skills for AI agents."])
        self.assertIn("# Agent Skills", payload["original_markdown"])
        self.assertIn(
            "![Demo](https://raw.githubusercontent.com/openai/agent-kit/main/assets/demo.png)",
            payload["original_markdown"],
        )
        self.assertIn(
            "[AI agents](https://github.com/openai/agent-kit/blob/main/docs/agents.md)",
            payload["original_markdown"],
        )

        with patch("urllib.request.urlopen", side_effect=TimeoutError("network timeout")):
            failed = fetch_github_readme("openai/agent-kit")

        self.assertEqual(failed["readme_status"], "failed")
        self.assertIn("network timeout", failed["readme_error"])

    def test_fetch_github_readme_prefers_root_chinese_readme(self):
        root_payload = [
            {
                "type": "file",
                "name": "README.md",
                "url": "https://api.github.com/repos/tencent/example/contents/README.md",
            },
            {
                "type": "file",
                "name": "README_CN.md",
                "url": "https://api.github.com/repos/tencent/example/contents/README_CN.md",
            },
        ]
        zh_readme = "# 中文说明\n\n![架构](docs/arch.png)\n\n阅读[快速开始](docs/start.md)。"
        zh_payload = {
            "name": "README_CN.md",
            "content": b64encode(zh_readme.encode("utf-8")).decode("ascii"),
            "encoding": "base64",
            "download_url": "https://raw.githubusercontent.com/tencent/example/main/README_CN.md",
            "html_url": "https://github.com/tencent/example/blob/main/README_CN.md",
        }

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return __import__("json").dumps(self.payload).encode("utf-8")

        def fake_urlopen(request, timeout=20):
            if request.full_url.endswith("/contents"):
                return FakeResponse(root_payload)
            if request.full_url.endswith("/contents/README_CN.md"):
                return FakeResponse(zh_payload)
            raise AssertionError(f"unexpected request: {request.full_url}")

        with patch("urllib.request.urlopen", side_effect=fake_urlopen) as urlopen:
            payload = fetch_github_readme("tencent/example")

        requested_urls = [call.args[0].full_url for call in urlopen.call_args_list]
        self.assertEqual(
            requested_urls,
            [
                "https://api.github.com/repos/tencent/example/contents",
                "https://api.github.com/repos/tencent/example/contents/README_CN.md",
            ],
        )
        self.assertEqual(payload["readme_status"], "ok")
        self.assertEqual(payload["readme_name"], "README_CN.md")
        self.assertEqual(payload["readme_language"], "zh")
        self.assertEqual(payload["readme_selection"], "preferred_zh_readme")
        self.assertIn("# 中文说明", payload["original_markdown"])
        self.assertIn(
            "![架构](https://raw.githubusercontent.com/tencent/example/main/docs/arch.png)",
            payload["original_markdown"],
        )
        self.assertIn(
            "[快速开始](https://github.com/tencent/example/blob/main/docs/start.md)",
            payload["original_markdown"],
        )

    def test_fetch_github_readme_falls_back_when_chinese_readme_fails(self):
        root_payload = [
            {
                "type": "file",
                "name": "README_zh.md",
                "url": "https://api.github.com/repos/tencent/example/contents/README_zh.md",
            }
        ]
        default_payload = {
            "name": "README.md",
            "content": b64encode("# English README\n\nDefault project docs.".encode("utf-8")).decode("ascii"),
            "encoding": "base64",
            "download_url": "https://raw.githubusercontent.com/tencent/example/main/README.md",
            "html_url": "https://github.com/tencent/example/blob/main/README.md",
        }

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return __import__("json").dumps(self.payload).encode("utf-8")

        def fake_urlopen(request, timeout=20):
            if request.full_url.endswith("/contents"):
                return FakeResponse(root_payload)
            if request.full_url.endswith("/contents/README_zh.md"):
                raise TimeoutError("zh readme timeout")
            if request.full_url.endswith("/readme"):
                return FakeResponse(default_payload)
            raise AssertionError(f"unexpected request: {request.full_url}")

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            payload = fetch_github_readme("tencent/example")

        self.assertEqual(payload["readme_status"], "ok")
        self.assertEqual(payload["readme_name"], "README.md")
        self.assertEqual(payload["readme_language"], "en")
        self.assertEqual(payload["readme_selection"], "default_readme")
        self.assertIn("# English README", payload["original_markdown"])
        # 中文版存在但这次没抓到，必须标记可重试，否则英文版会永久固化
        self.assertEqual(payload["readme_zh_probe"], "failed")

    def test_fetch_github_readme_marks_zh_probe_failed_when_rate_limited(self):
        # GitHub 匿名 API 限流（60 次/小时）时 root contents 请求 403，
        # 降级到默认英文 README 不能悄悄把结果当成终态——真实案例：
        # TencentCloud 仓库有 README_CN.md 却永久存成了英文版。
        default_payload = {
            "name": "README.md",
            "content": b64encode("# English README\n\nDefault docs.".encode("utf-8")).decode("ascii"),
            "encoding": "base64",
            "download_url": "https://raw.githubusercontent.com/tencent/example/main/README.md",
            "html_url": "https://github.com/tencent/example/blob/main/README.md",
        }

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return __import__("json").dumps(self.payload).encode("utf-8")

        def fake_urlopen(request, timeout=20):
            if request.full_url.endswith("/contents"):
                raise urllib.error.HTTPError(
                    request.full_url, 403, "rate limit exceeded", None, io.BytesIO(b"rate limit")
                )
            if request.full_url.endswith("/readme"):
                return FakeResponse(default_payload)
            raise AssertionError(f"unexpected request: {request.full_url}")

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            payload = fetch_github_readme("tencent/example")

        self.assertEqual(payload["readme_status"], "ok")
        self.assertEqual(payload["readme_selection"], "default_readme")
        self.assertEqual(payload["readme_zh_probe"], "failed")

    def test_fetch_github_readme_zh_probe_none_when_repo_has_no_chinese_readme(self):
        root_payload = [
            {"type": "file", "name": "README.md", "url": "https://api.github.com/repos/o/r/contents/README.md"}
        ]
        default_payload = {
            "name": "README.md",
            "content": b64encode("# English only\n\nDocs.".encode("utf-8")).decode("ascii"),
            "encoding": "base64",
            "download_url": "https://raw.githubusercontent.com/o/r/main/README.md",
            "html_url": "https://github.com/o/r/blob/main/README.md",
        }

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return __import__("json").dumps(self.payload).encode("utf-8")

        def fake_urlopen(request, timeout=20):
            if request.full_url.endswith("/contents"):
                return FakeResponse(root_payload)
            if request.full_url.endswith("/readme"):
                return FakeResponse(default_payload)
            raise AssertionError(f"unexpected request: {request.full_url}")

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            payload = fetch_github_readme("o/r")

        self.assertEqual(payload["readme_status"], "ok")
        # 确认过仓库确实没有中文 README，不需要重试
        self.assertEqual(payload["readme_zh_probe"], "none")

    def test_fetch_github_readme_limits_original_markdown_size(self):
        readme = "# Agent Skills\n\n" + ("Long README paragraph.\n\n" * 6000)
        api_payload = {
            "content": b64encode(readme.encode("utf-8")).decode("ascii"),
            "encoding": "base64",
            "download_url": "https://raw.githubusercontent.com/openai/agent-kit/main/README.md",
            "html_url": "https://github.com/openai/agent-kit/blob/main/README.md",
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return __import__("json").dumps(api_payload).encode("utf-8")

        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            payload = fetch_github_readme("openai/agent-kit")

        self.assertEqual(payload["readme_status"], "ok")
        self.assertLessEqual(len(payload["original_markdown"]), 80_000)
        self.assertTrue(payload["original_markdown"].startswith("# Agent Skills"))

    def test_parse_hn_hits_filters_ai_as_word_and_limits_after_filtering(self):
        source = Source(
            id="hacker_news",
            name="Hacker News",
            source_role="signal",
            tier="T2",
            type="hn",
            category="community",
            url="https://hn.algolia.com/api/v1/search_by_date?query=AI&tags=story",
            homepage="https://news.ycombinator.com",
            allowed_domains=["news.ycombinator.com", "hn.algolia.com"],
            affects_heat_score=True,
            can_be_main_source=True,
            config={"query_terms": ["ai", "llm", "openai"]},
        )
        hits = [
            {
                "objectID": "1",
                "title": "Taiwan Aims To Go Bilingual by 2030",
                "url": "https://example.com/aims",
                "author": "user1",
                "created_at": "2026-07-01T10:00:00Z",
                "points": 10,
            },
            {
                "objectID": "2",
                "title": "Modern AI foundations videos",
                "url": "https://example.com/modern-ai",
                "author": "user2",
                "created_at": "2026-07-01T11:00:00Z",
                "points": 10,
            },
            {
                "objectID": "3",
                "title": "OpenAI releases an agent benchmark",
                "url": "https://example.com/openai-agent",
                "author": "user3",
                "created_at": "2026-07-01T12:00:00Z",
                "points": 10,
            },
        ]

        articles = parse_hn_hits(hits, source, limit=2)

        self.assertEqual(
            [article.title for article in articles],
            ["Modern AI foundations videos", "OpenAI releases an agent benchmark"],
        )

    def test_parse_huggingface_papers_builds_articles_and_filters_by_query_terms(self):
        source = Source(
            id="huggingface_papers",
            name="HuggingFace Trending Papers",
            source_role="authority",
            tier="T1_5",
            type="huggingface_papers",
            category="research",
            url="https://huggingface.co/api/daily_papers",
            homepage="https://huggingface.co/papers",
            allowed_domains=["huggingface.co"],
            can_be_main_source=True,
            config={"query_terms": ["agent"]},
        )
        payload = [
            {
                "paper": {
                    "id": "2607.00001",
                    "title": "A Survey of Reasoning in LLMs",
                    "summary": "We study reasoning.",
                    "authors": [{"name": "Alice"}, {"name": "Bob"}],
                    "publishedAt": "2026-07-10T00:00:00.000Z",
                    "upvotes": 5,
                },
                "numComments": 2,
            },
            {
                "paper": {
                    "id": "2607.00002",
                    "title": "Building Autonomous Agents",
                    "summary": "We build an agent.",
                    "authors": [{"name": "Carol"}],
                    "publishedAt": "2026-07-11T00:00:00.000Z",
                    "upvotes": 8,
                },
                "numComments": 0,
            },
        ]

        articles = parse_huggingface_papers(payload, source)

        self.assertEqual(len(articles), 1)
        article = articles[0]
        self.assertEqual(article.title, "Building Autonomous Agents")
        self.assertEqual(article.source_url, "https://huggingface.co/papers/2607.00002")
        self.assertEqual(article.author, "Carol")
        self.assertEqual(article.raw_score["upvotes"], 8)

    def test_parse_huggingface_papers_skips_entries_missing_id_or_title(self):
        source = Source(
            id="huggingface_papers",
            name="HuggingFace Trending Papers",
            source_role="authority",
            tier="T1_5",
            type="huggingface_papers",
            category="research",
            url="https://huggingface.co/api/daily_papers",
            homepage="https://huggingface.co/papers",
            allowed_domains=["huggingface.co"],
            can_be_main_source=True,
        )
        payload = [{"paper": {"id": "", "title": "No id"}}, {"paper": {"id": "x"}}]

        articles = parse_huggingface_papers(payload, source)

        self.assertEqual(articles, [])

    def test_parse_attentionvc_entries_builds_x_status_urls_and_filters_language(self):
        source = Source(
            id="attentionvc_x",
            name="X 推文 (AttentionVC)",
            source_role="signal",
            tier="T2",
            type="attentionvc",
            category="community",
            url="https://reply-vc-90459984647.us-central1.run.app/v1/articles/leaderboard",
            homepage="https://x.com",
            allowed_domains=["x.com"],
            affects_heat_score=True,
            can_be_main_source=True,
        )
        payload = {
            "entries": [
                {
                    "tweetId": "111",
                    "title": "English AI post",
                    "tweetCreatedAt": "2026-07-10T07:57:13.000Z",
                    "author": {"handle": "someone", "followers": 1000},
                    "viewCount": 5000,
                    "likeCount": 200,
                    "retweetCount": 10,
                    "previewText": "Some preview text.",
                    "langsDetected": ["en"],
                },
                {
                    "tweetId": "222",
                    "title": "非英语帖子",
                    "author": {"handle": "other"},
                    "langsDetected": ["ja"],
                },
            ]
        }

        articles = parse_attentionvc_entries(payload, source)

        self.assertEqual(len(articles), 1)
        article = articles[0]
        self.assertEqual(article.source_url, "https://x.com/someone/status/111")
        self.assertEqual(article.raw_score["likes"], 200)

    def test_parse_v2ex_topics_filters_by_min_replies_and_sorts_by_replies(self):
        source = Source(
            id="v2ex_ai",
            name="V2EX",
            source_role="signal",
            tier="T2",
            type="v2ex",
            category="community",
            url="https://www.v2ex.com/api/topics/show.json?node_name=openai",
            homepage="https://www.v2ex.com/go/openai",
            allowed_domains=["v2ex.com"],
            language="zh",
            affects_heat_score=True,
            can_be_main_source=True,
            config={"min_replies": 2},
        )
        payload = [
            {
                "id": 1,
                "title": "零回复帖子",
                "url": "https://www.v2ex.com/t/1",
                "replies": 0,
                "created": 1783900000,
                "member": {"username": "u1"},
                "node": {"name": "openai"},
            },
            {
                "id": 2,
                "title": "热门帖子",
                "url": "https://www.v2ex.com/t/2",
                "content": "内容",
                "replies": 20,
                "created": 1783900001,
                "member": {"username": "u2"},
                "node": {"name": "openai"},
            },
            {
                "id": 3,
                "title": "次热门帖子",
                "url": "https://www.v2ex.com/t/3",
                "replies": 5,
                "created": 1783900002,
                "member": {"username": "u3"},
                "node": {"name": "openai"},
            },
        ]

        articles = parse_v2ex_topics(payload, source)

        self.assertEqual([a.title for a in articles], ["热门帖子", "次热门帖子"])

    def test_main_content_region_prefers_content_marker_div_over_main(self):
        # 真实案例（HuggingFace 博客）：正文在 <div class="blog-content …">，
        # 评论区（Community/Sign up）和推荐卡片与它并列在同一个 <main> 里，
        # 页面没有可用的 <article>/<aside> 语义标签——选区必须缩到正文容器，
        # 否则评论区 UI 文案会被当成正文段落
        html = """<!DOCTYPE html><html><body><main>
        <div class="blog-content copiable-code-container prose mx-auto">
          <p>vLLM now runs transformers models at native speed thanks to the new
          backend, which reuses attention kernels and the paged KV cache.</p>
          <p>Benchmarks across four model families show throughput parity with the
          hand-optimized implementations while keeping full API compatibility.</p>
        </div>
        <div class="mb-4 rounded-lg border">
          <h4>Community</h4>
          <p>Start discussing this article</p>
          <p>· Sign up or log in to comment</p>
        </div>
        <div class="rounded-lg border">
          <p>Datasets mentioned in this article</p>
        </div>
        </main></body></html>"""

        region = main_content_region(html)

        self.assertIsNotNone(region)
        self.assertIn("native speed", region)
        self.assertNotIn("Sign up or log in", region)
        self.assertNotIn("Datasets mentioned", region)

    def test_prefer_full_page_content_flips_language_to_match_fetched_body(self):
        # aihot 聚合源标 zh（feed 摘要是中文），但"阅读原文"多为英文页面；
        # 全文替换后语言标记必须跟随正文，否则翻译管道（只认 en）不会翻它
        import tempfile

        from app.crawlers.page_content import prefer_full_page_content

        source = Source(
            id="aihot_feed",
            name="AI HOT 每日精选",
            source_role="aggregator",
            tier="T3",
            type="rss",
            category="media",
            url="https://aihot.virxact.com/feed.xml",
            homepage="https://aihot.virxact.com",
            allowed_domains=["aihot.virxact.com"],
            language="zh",
            can_be_main_source=False,
        )
        article = normalize_article(
            source=source,
            source_url="https://casp.ac/reports/ai-enabled-terrorism",
            title="How groups use frontier AI",
            content="中文摘要：报告讨论了前沿 AI 的滥用问题。",
            author=None,
            published_at=datetime(2026, 7, 10, 22, tzinfo=timezone.utc),
            language=source.language,
            raw_score={},
            metadata={},
        )
        page_html = """<!DOCTYPE html><html><body><article>
        <p>Frontier AI systems are increasingly capable, and this report examines
        how extremist groups experiment with them for propaganda and recruiting.</p>
        <p>The authors reviewed dozens of operational incidents and interviewed
        analysts to understand where current safeguards fall short in practice.</p>
        </article></body></html>"""

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.crawlers.page_content.fetch_url_text", return_value=page_html):
                prefer_full_page_content(article, cache_dir=Path(tmpdir))

        self.assertEqual(article.metadata.get("content_origin"), "full_page")
        self.assertIn("Frontier AI systems", article.content)
        self.assertEqual(article.language, "en")

    def test_prefer_full_page_content_keeps_zh_language_for_chinese_body(self):
        import tempfile

        from app.crawlers.page_content import prefer_full_page_content

        source = Source(
            id="ithome",
            name="IT之家",
            source_role="signal",
            tier="T2",
            type="rss",
            category="media",
            url="https://www.ithome.com/rss/",
            homepage="https://www.ithome.com",
            allowed_domains=["ithome.com"],
            language="zh",
        )
        article = normalize_article(
            source=source,
            source_url="https://www.ithome.com/0/973/803.htm",
            title="国产大模型发布",
            content="摘要",
            author=None,
            published_at=datetime(2026, 7, 10, 22, tzinfo=timezone.utc),
            language=source.language,
            raw_score={},
            metadata={},
        )
        page_html = """<!DOCTYPE html><html><body><article>
        <p>今天发布的国产大模型在多项公开基准测试上刷新了行业纪录，模型支持超长上下文窗口
        与多模态输入输出能力，面向开发者全面开放应用编程接口，并同步提供企业级私有化部署方案，
        覆盖在线推理与继续训练两大类使用场景，官方文档给出了完整的迁移指引和示例代码仓库。</p>
        <p>官方同时公布了详细的价格档位与调用配额策略，早期接入的多个开发团队反馈整体积极，
        社区讨论集中在推理延迟与中文语料质量两个方面，已有多家企业宣布将现有业务迁移至该模型。</p>
        </article></body></html>"""

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.crawlers.page_content.fetch_url_text", return_value=page_html):
                prefer_full_page_content(article, cache_dir=Path(tmpdir))

        self.assertEqual(article.metadata.get("content_origin"), "full_page")
        self.assertEqual(article.language, "zh")

    def test_prefer_full_page_content_skips_known_unfetchable_domain(self):
        # mp.weixin.qq.com/m.qq.com sit behind an anti-crawler verification
        # wall - fetching them risks storing the verification page's own
        # text as if it were the article body. Must not even attempt the
        # network fetch, and must leave the article's existing (thin feed
        # summary) content untouched.
        import tempfile

        from app.crawlers.page_content import prefer_full_page_content

        source = Source(
            id="some_wechat_source",
            name="某公众号聚合",
            source_role="signal",
            tier="T2",
            type="rss",
            category="media",
            url="https://example.com/rss",
            homepage="https://example.com",
            allowed_domains=["example.com"],
            language="zh",
        )
        article = normalize_article(
            source=source,
            source_url="https://mp.weixin.qq.com/s/abc123",
            title="公众号文章标题",
            content="薄摘要占位内容",
            author=None,
            published_at=datetime(2026, 7, 10, 22, tzinfo=timezone.utc),
            language=source.language,
            raw_score={},
            metadata={},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.crawlers.page_content.fetch_url_text") as mock_fetch:
                prefer_full_page_content(article, cache_dir=Path(tmpdir))

        mock_fetch.assert_not_called()
        self.assertEqual(article.content, "薄摘要占位内容")
        self.assertNotIn("content_origin", article.metadata)
        self.assertNotIn("original_paragraphs", article.metadata)

    def test_parse_hn_hits_drops_low_engagement_posts_by_default(self):
        # 实测两例（1分0评的 SPA 空壳、广告落地页）：HN 的价值信号就是
        # points/comments，低于门槛的帖子不该成为候选去花 AI 评分
        source = Source(
            id="hacker_news",
            name="Hacker News",
            source_role="signal",
            tier="T2",
            type="hn",
            category="community",
            url="https://hn.algolia.com/api/v1/search_by_date?query=AI&tags=story",
            homepage="https://news.ycombinator.com",
            allowed_domains=["news.ycombinator.com", "hn.algolia.com"],
            config={"query_terms": ["ai", "openai"]},
        )
        hits = [
            {
                "objectID": "1",
                "title": "OpenAI agent self promo",
                "url": "https://example.com/promo",
                "author": "u1",
                "created_at": "2026-07-01T10:00:00Z",
                "points": 1,
                "num_comments": 0,
            },
            {
                "objectID": "2",
                "title": "OpenAI agent hot story",
                "url": "https://example.com/hot",
                "author": "u2",
                "created_at": "2026-07-01T11:00:00Z",
                "points": 25,
                "num_comments": 0,
            },
            {
                "objectID": "3",
                "title": "OpenAI agent discussed story",
                "url": "https://example.com/discussed",
                "author": "u3",
                "created_at": "2026-07-01T12:00:00Z",
                "points": 2,
                "num_comments": 7,
            },
        ]

        articles = parse_hn_hits(hits, source)

        self.assertEqual(
            [article.title for article in articles],
            ["OpenAI agent hot story", "OpenAI agent discussed story"],
        )

    def test_parse_hn_hits_engagement_threshold_is_configurable(self):
        source = Source(
            id="hacker_news",
            name="Hacker News",
            source_role="signal",
            tier="T2",
            type="hn",
            category="community",
            url="https://hn.algolia.com/api/v1/search_by_date?query=AI&tags=story",
            homepage="https://news.ycombinator.com",
            allowed_domains=["news.ycombinator.com", "hn.algolia.com"],
            config={"query_terms": ["openai"], "min_points": 0, "min_comments": 0},
        )
        hits = [
            {
                "objectID": "1",
                "title": "OpenAI agent brand new post",
                "url": "https://example.com/new",
                "author": "u1",
                "created_at": "2026-07-01T10:00:00Z",
                "points": 0,
                "num_comments": 0,
            }
        ]

        articles = parse_hn_hits(hits, source)

        self.assertEqual(len(articles), 1)

    def test_page_fetch_throttles_same_domain_requests(self):
        # 正文拉取现在跑在 20 并发的 AI 池里(2026-07-12 流程重排),
        # 同域真实请求必须保持最小间隔,防止打爆 Reddit 这类限流站点
        import tempfile
        import time as time_module

        from app.crawlers import page_content

        html = """<!DOCTYPE html><html><head><title>Throttle test page</title></head>
<body><article><h1>Throttle test page</h1>
<p>Body paragraph one with enough real prose text to pass the extraction
threshold used by the article content extractor in this project.</p>
<p>Body paragraph two, also long enough to be treated as a legitimate
paragraph of article prose rather than boilerplate or navigation.</p>
</article></body></html>"""

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(page_content, "_DOMAIN_MIN_INTERVAL_SECONDS", 0.3), patch(
                "app.crawlers.page_content.fetch_url_text", return_value=html
            ):
                started = time_module.monotonic()
                page_content.fetch_page_payload(
                    "https://reddit.example/post-1", cache_dir=Path(tmpdir)
                )
                page_content.fetch_page_payload(
                    "https://reddit.example/post-2", cache_dir=Path(tmpdir)
                )
                elapsed = time_module.monotonic() - started
                # 缓存命中不节流
                cache_started = time_module.monotonic()
                page_content.fetch_page_payload(
                    "https://reddit.example/post-1", cache_dir=Path(tmpdir)
                )
                cached_elapsed = time_module.monotonic() - cache_started

        self.assertGreaterEqual(elapsed, 0.3)
        self.assertLess(cached_elapsed, 0.1)

    def test_hacker_news_crawler_defers_body_fetch_to_pipeline(self):
        # 流程重排(2026-07-12 晚):HN 的 fetch() 只拉 Algolia 元数据,
        # 外链正文延迟到预筛通过后由 pipeline 拉取(标 body_fetch=deferred)
        import tempfile

        source = Source(
            id="hacker_news",
            name="Hacker News",
            source_role="signal",
            tier="T2",
            type="hn",
            category="community",
            url="https://hn.algolia.com/api/v1/search_by_date?query=AI&tags=story",
            homepage="https://news.ycombinator.com",
            allowed_domains=["news.ycombinator.com", "hn.algolia.com"],
            config={"query_terms": ["ai"]},
        )
        hits_payload = {
            "hits": [
                {
                    "objectID": "1",
                    "title": "AI Gets a Cerebellum",
                    "url": "https://example.com/ai-cerebellum",
                    "author": "user1",
                    "created_at": "2026-07-01T10:00:00Z",
                    "points": 42,
                    "num_comments": 17,
                }
            ]
        }
        page_html = """<!DOCTYPE html>
<html><head><title>AI Gets a Cerebellum</title></head>
<body><article>
<h1>AI Gets a Cerebellum</h1>
<p>Researchers built a new module with stronger reasoning for robots, drawing
directly on how biological cerebellums coordinate fine motor control.</p>
<p>It coordinates fine motor control across many simulated limbs at once,
improving balance and reaction time well beyond earlier baseline models
tested on the same benchmark suite.</p>
</article></body></html>
"""

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return __import__("json").dumps(hits_payload).encode("utf-8")

        def fail_page_fetch(url, **kwargs):
            raise AssertionError("fetch() must not pull article pages any more")

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("urllib.request.urlopen", return_value=FakeResponse()), patch(
                "app.crawlers.page_content.fetch_url_text", side_effect=fail_page_fetch
            ):
                crawler = HackerNewsCrawler(source, page_cache_dir=Path(tmpdir))
                articles = crawler.fetch(limit=5)

        self.assertEqual(articles[0].metadata.get("body_fetch"), "deferred")
        self.assertNotIn("stronger reasoning", articles[0].content)

    def test_qbitai_profile_extracts_byline_lead_and_strict_article_boundary(self):
        html = """
        <html><body>
          <div class="article">
            <h1>不是吧OpenAI首款硬件吹半天就是个AI音箱？？</h1>
            <div class="article_info">
              <span class="author"><img class="avatar avatar-200" width="200" height="200"
                src="/wp-content/themes/liangziwei/imagesnew/head.jpg"><a rel="author"
                href="/author/yuyang">鱼羊</a></span>
              <span class="date">2026-07-15</span><span class="time">12:46:18</span>
              <span class="from">来源：<a href="https://www.qbitai.com">量子位</a></span>
            </div>
            <div class="zhaiyao"><p>难怪苹果急眼了</p></div>
            <blockquote><p>鱼羊 发自 凹非寺</p><p>量子位 | 公众号 QbitAI</p></blockquote>
            <p><s>听上去，它肯定不能是长这样吧：</s></p>
            <p><img src="https://i.qbitai.com/content.webp"></p>
          </div>
          <div class="person_box"><p>作者文章列表</p><img src="/head.jpg"></div>
          <section class="related"><p>热门文章</p></section>
        </body></html>
        """
        region = html
        content = extract_article_content(
            region,
            base_url="https://www.qbitai.com/2026/07/450385.html",
            title="不是吧OpenAI首款硬件吹半天就是个AI音箱？？",
        )

        self.assertEqual(content["content_profile"], "qbitai-v1")
        self.assertEqual(content["original_blocks"][0]["type"], "byline")
        self.assertEqual(content["original_blocks"][0]["author"]["name"], "鱼羊")
        self.assertEqual(content["original_blocks"][1]["type"], "callout")
        self.assertEqual(content["original_blocks"][2]["kind"], "quote")
        self.assertIn("<del>", content["original_blocks"][3]["html"])
        self.assertEqual([image["url"] for image in content["original_images"]], ["https://i.qbitai.com/content.webp"])
        self.assertNotIn("热门文章", content["original_text"])
        self.assertNotIn("作者文章列表", content["original_text"])

    def test_github_blog_profile_ignores_recommendation_article_cards(self):
        from app.crawlers.sitemap import main_content_region

        page = """
        <html><body><main>
          <section class="post__content">
            <p>Give an agent better tools and it should do better work. This is the real opening paragraph of the requested GitHub Blog article.</p>
            <p>When Copilot code review switched tools, benchmark cost increased and fewer useful issues were caught. The team inspected traces and changed the review workflow.</p>
            <h2>The trace revealed a browsing loop</h2>
            <p>The revised instructions started from the pull request diff, batched discovery, and read only the narrow code ranges needed for evidence.</p>
            <p>The result was roughly twenty percent lower average review cost while maintaining review quality across the same evaluation tasks.</p>
            <div class="post-content-cta"><p>Try GitHub Copilot now</p></div>
            <section class="my-6 my-md-8 mt-md-0">
              <hr class="post-tags-separator" />
              <h2>Tags:</h2>
              <ul class="post-tags"><li>GitHub Copilot</li><li>LLMs</li></ul>
            </section>
            <div class="mt-8 mb-8 mb-md-0">
              <h2>Written by</h2>
              <article class="author-bio">
                <h3>Napalys Klicius</h3>
                <p>@Napalys</p>
                <p>Napalys Klicius is a Software Engineer at GitHub building agentic systems.</p>
              </article>
            </div>
          </section>
          <article class="post-card">
            <h3>Evaluating performance and efficiency of the GitHub Copilot agentic harness across models and tasks</h3>
            <p>Explore how the GitHub Copilot agentic harness delivers strong results across multiple benchmarks.</p>
          </article>
        </main></body></html>
        """
        url = "https://github.blog/ai-and-ml/github-copilot/example-post/"
        region = main_content_region(page, base_url=url)
        content = extract_article_content(region, base_url=url, title="Requested article")

        self.assertEqual(content["content_profile"], "github-blog-v1")
        self.assertIn("real opening paragraph", content["original_text"])
        self.assertIn("twenty percent lower", content["original_text"])
        self.assertNotIn("Evaluating performance", content["original_text"])
        self.assertNotIn("Try GitHub Copilot now", content["original_text"])
        self.assertNotIn("Tags:", content["original_text"])
        self.assertNotIn("Written by", content["original_text"])
        self.assertNotIn("Napalys Klicius", content["original_text"])

    def test_arxiv_profile_keeps_only_the_abstract(self):
        page = """
        <html><body><main>
          <h1 class="title"><span class="descriptor">Title:</span>A useful AI paper</h1>
          <div class="authors">Authors: Ada Researcher</div>
          <blockquote class="abstract mathjax">
            <span class="descriptor">Abstract:</span>
            This paper introduces a robust AI method and evaluates it across three benchmarks.
            The results improve accuracy while reducing inference cost.
          </blockquote>
          <table><tr><td>Subjects:</td><td>Artificial Intelligence (cs.AI)</td></tr></table>
          <h2>Submission history</h2>
          <p>[v1] Thu, 16 Jul 2026</p>
          <h2>Access Paper:</h2>
          <ul><li>View PDF</li><li>TeX Source</li></ul>
        </main></body></html>
        """
        url = "https://arxiv.org/abs/2607.14086v1"
        content = extract_article_content(page, base_url=url, title="A useful AI paper")

        self.assertEqual(content["content_profile"], "arxiv-abstract-v1")
        self.assertEqual(len(content["original_blocks"]), 1)
        self.assertIn("introduces a robust AI method", content["original_text"])
        self.assertNotIn("Subjects", content["original_text"])
        self.assertNotIn("Submission history", content["original_text"])
        self.assertNotIn("View PDF", content["original_text"])

    def test_deepmind_profile_preserves_paragraphs_and_drops_related_posts(self):
        page = """
        <html><body><main id="page-content">
          <section class="grid section-default">
            <div class="grid__inner"><div class="rich-text">
              <p>The first paragraph explains the biosecurity challenge.</p>
              <p>The second paragraph introduces the joint response.</p>
              <h2>Inside our bioresilience program</h2>
              <p>The program supports prevention, detection, and response.</p>
              <h4>Prevent:</h4>
              <p>Models follow a four-step safety process.</p>
              <h4>Detect:</h4>
              <p>Agents help identify emerging threats faster.</p>
            </div></div>
          </section>
          <section class="grid section-default">
            <div class="section-header__heading">
              <h2 class="section-header__title">Related posts</h2>
            </div>
            <article class="card"><h3>Another DeepMind article</h3></article>
          </section>
        </main></body></html>
        """
        content = extract_article_content(
            page,
            base_url="https://deepmind.google/blog/our-approach-to-bioresilience/",
        )

        self.assertEqual(content["content_profile"], "deepmind-blog-v1")
        self.assertEqual(
            [block["type"] for block in content["original_blocks"]],
            [
                "paragraph",
                "paragraph",
                "heading",
                "paragraph",
                "heading",
                "paragraph",
                "heading",
                "paragraph",
            ],
        )
        self.assertEqual(
            content["original_paragraphs"][:2],
            [
                "The first paragraph explains the biosecurity challenge.",
                "The second paragraph introduces the joint response.",
            ],
        )
        self.assertNotIn("Related posts", content["original_text"])
        self.assertNotIn("Another DeepMind article", content["original_text"])

    def test_deepmind_profile_preserves_safe_youtube_and_direct_videos(self):
        page = """
        <html><body><main id="page-content">
          <section class="grid section-default">
            <div class="rich-text"><p>Before the videos.</p></div>
            <div class="media-embed">
              <iframe
                src="https://www.youtube.com/embed/xJ94HFpGM4Y?enablejsapi=1&origin=https://deepmind.google"
                title="ATL Saathi overview"
                width="200"
                height="113"></iframe>
            </div>
            <iframe src="https://untrusted.example/embed/tracker"></iframe>
            <figure class="media-video-figure">
              <div data-width="3840" data-height="2160">
                <video autoplay loop muted poster="/poster.jpg">
                  <source
                    data-src="https://storage.googleapis.com/example/animation.webm#t=0.1"
                    type="video/webm">
                  Your browser does not support the video tag.
                </video>
                <noscript>
                  <video><source src="https://storage.googleapis.com/example/animation.webm" type="video/webm"></video>
                </noscript>
              </div>
              <figcaption><p>Animation of the project planner.</p></figcaption>
            </figure>
            <div class="rich-text"><p>After the videos.</p></div>
          </section>
        </main></body></html>
        """
        content = extract_article_content(
            page,
            base_url="https://deepmind.google/blog/example/",
        )

        videos = [
            block
            for block in content["original_blocks"]
            if block["type"] == "video"
        ]
        self.assertEqual(len(videos), 2)
        self.assertEqual(
            videos[0],
            {
                "type": "video",
                "provider": "youtube",
                "url": "https://www.youtube-nocookie.com/embed/xJ94HFpGM4Y",
                "title": "ATL Saathi overview",
                "width": 200,
                "height": 113,
            },
        )
        self.assertEqual(videos[1]["provider"], "file")
        self.assertEqual(videos[1]["mime_type"], "video/webm")
        self.assertEqual(videos[1]["caption"], "Animation of the project planner.")
        self.assertTrue(videos[1]["autoplay"])
        self.assertTrue(videos[1]["loop"])
        self.assertTrue(videos[1]["muted"])
        self.assertNotIn("untrusted.example", str(content["original_blocks"]))
        self.assertNotIn("browser does not support", content["original_text"].lower())

    def test_dom_semantic_blocks_and_safety(self):
        html = """
        <article>
          <p><a href="javascript:alert(1)" onclick="alert(1)">危险链接</a>，<sup>2</sup></p>
          <ul><li><strong>第一项</strong></li><li>第二项</li></ul>
          <pre><code class="language-python">print('ok')</code></pre>
          <table><tr><th>名称</th><th>值</th></tr><tr><td>A</td><td>1</td></tr></table>
          <hr><script>alert(1)</script>
        </article>
        """
        content = extract_article_content(html, base_url="https://example.com/post")
        types = [block["type"] for block in content["original_blocks"]]
        self.assertEqual(types, ["paragraph", "list", "code", "table", "divider"])
        self.assertNotIn("javascript:", content["original_blocks"][0].get("html", ""))
        self.assertNotIn("onclick", content["original_blocks"][0].get("html", ""))
        self.assertEqual(content["original_blocks"][2]["language"], "python")


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from base64 import b64encode
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.crawlers.base import normalize_article
from app.crawlers.article_content import extract_article_content
from app.crawlers.github import parse_github_trending
from app.crawlers.github_readme import (
    fetch_github_readme,
    markdown_to_original_payload,
    repo_path_from_github_url,
)
from app.crawlers.hn import parse_hn_hits
from app.crawlers.rss import parse_rss
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
            },
            {
                "objectID": "2",
                "title": "Modern AI foundations videos",
                "url": "https://example.com/modern-ai",
                "author": "user2",
                "created_at": "2026-07-01T11:00:00Z",
            },
            {
                "objectID": "3",
                "title": "OpenAI releases an agent benchmark",
                "url": "https://example.com/openai-agent",
                "author": "user3",
                "created_at": "2026-07-01T12:00:00Z",
            },
        ]

        articles = parse_hn_hits(hits, source, limit=2)

        self.assertEqual(
            [article.title for article in articles],
            ["Modern AI foundations videos", "OpenAI releases an agent benchmark"],
        )
        self.assertEqual([article.metadata["hn_object_id"] for article in articles], ["2", "3"])


if __name__ == "__main__":
    unittest.main()

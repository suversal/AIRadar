from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
except ModuleNotFoundError:  # pragma: no cover
    create_engine = None

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover
    TestClient = None


@unittest.skipIf(create_engine is None, "SQLAlchemy is not installed")
class ManualArticleServiceTests(unittest.TestCase):
    def setUp(self):
        from app.db.models import Base

        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, future=True)

    @staticmethod
    def _document(text="OpenAI 发布了新的 AI Agent 模型，并公布了完整能力、使用方式、接口参数、评测结果和面向开发者的上线计划。"):
        return {
            "type": "doc",
            "content": [
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "产品更新"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": text, "marks": [{"type": "bold"}]}]},
                {"type": "image", "attrs": {"src": "https://img.example/a.png", "alt": "截图"}},
            ],
        }

    def test_editor_submission_stays_private_until_published(self):
        from app.db.models import ProcessedArticleModel, RawArticleModel
        from app.repositories.radar_repository import RadarRepository
        from app.services.ai_service import FakeAIProvider
        from app.services.manual_articles import create_submission, process_submission, publish_submission

        with self.Session() as session:
            repository = RadarRepository(session)
            submission = create_submission(
                repository,
                {
                    "mode": "editor",
                    "editor_document": self._document(),
                    "manual_fields": {"title": "管理员标题", "summary_zh": "管理员摘要"},
                    "selection_mode": "force_selected",
                },
            )
            self.assertIsNone(session.query(RawArticleModel).first())
            process_submission(repository, submission.id, ai_provider=FakeAIProvider())
            self.assertEqual(submission.processing_status, "ready")
            self.assertIsNone(session.query(RawArticleModel).first())

            publish_submission(repository, submission.id)
            session.commit()
            raw = session.query(RawArticleModel).one()
            processed = session.query(ProcessedArticleModel).one()

        self.assertEqual(raw.title, "管理员标题")
        self.assertEqual(processed.selection_origin, "admin")
        self.assertEqual(processed.status, "processed")

    def test_insufficient_editor_content_remains_failed_draft(self):
        from app.repositories.radar_repository import RadarRepository
        from app.services.ai_service import FakeAIProvider
        from app.services.manual_articles import create_submission, process_submission

        with self.Session() as session:
            repository = RadarRepository(session)
            submission = create_submission(
                repository,
                {"mode": "editor", "editor_document": self._document("短文")},
            )
            process_submission(repository, submission.id, ai_provider=FakeAIProvider())

        self.assertEqual(submission.processing_status, "failed")
        self.assertEqual(submission.last_error_code, "insufficient_content")
        self.assertEqual(submission.publication_status, "draft")

    def test_url_mode_rejects_non_http_url_before_fetch(self):
        from app.repositories.radar_repository import RadarRepository
        from app.services.manual_articles import SubmissionError, create_submission

        with self.Session() as session:
            with self.assertRaises(SubmissionError) as context:
                create_submission(
                    RadarRepository(session),
                    {"mode": "url", "original_url": "file:///etc/passwd"},
                )
        self.assertEqual(context.exception.code, "invalid_url")

    def test_submission_mode_is_derived_from_optional_url(self):
        from app.repositories.radar_repository import RadarRepository
        from app.services.manual_articles import create_submission, update_submission

        with self.Session() as session:
            submission = create_submission(
                RadarRepository(session),
                {"editor_document": self._document()},
            )
            self.assertEqual(submission.mode, "editor")

            update_submission(
                submission,
                {"original_url": "https://example.com/article"},
            )
            self.assertEqual(submission.mode, "url")

            update_submission(submission, {"original_url": None})
            self.assertEqual(submission.mode, "editor")

    def test_deleting_published_article_keeps_submission_as_draft(self):
        from app.db.models import ArticleSubmissionModel, RawArticleModel
        from app.repositories.radar_repository import RadarRepository
        from app.services.ai_service import FakeAIProvider
        from app.services.manual_articles import (
            create_submission,
            process_submission,
            publish_submission,
        )

        with self.Session() as session:
            repository = RadarRepository(session)
            submission = create_submission(
                repository,
                {
                    "mode": "editor",
                    "editor_document": self._document(),
                    "selection_mode": "force_selected",
                },
            )
            process_submission(repository, submission.id, ai_provider=FakeAIProvider())
            publish_submission(repository, submission.id)
            raw_id = submission.raw_article_id
            self.assertTrue(repository.delete_raw_article(f"a{raw_id[:12]}"))
            session.flush()
            stored = session.get(ArticleSubmissionModel, submission.id)
            raw_count = session.query(RawArticleModel).count()

        self.assertEqual(raw_count, 0)
        self.assertEqual(stored.publication_status, "draft")
        self.assertIsNone(stored.raw_article_id)

    def test_admin_selection_survives_automatic_upsert(self):
        from app.db.models import ProcessedArticleModel
        from app.models.domain import ProcessedArticle, ScoreDimensions
        from app.repositories.radar_repository import RadarRepository

        dims = ScoreDimensions(8, 8, 8, 8, 8, 8)
        first = ProcessedArticle(
            raw_article_id="a1", event_cluster_id=None, dimensions=dims, base_score=8,
            final_score=80, title_zh="A", one_line_summary="A", summary_zh="A",
            reason_zh="A", action_zh="A", category="industry", tags=[], selected=True,
            status="processed", selection_origin="admin", selection_reason="admin:force_selected",
        )
        automatic = ProcessedArticle(
            raw_article_id="a1", event_cluster_id=None, dimensions=dims, base_score=4,
            final_score=40, title_zh="B", one_line_summary="B", summary_zh="B",
            reason_zh="B", action_zh="B", category="industry", tags=[], selected=False,
            status="rejected", rejection_reason="below_threshold:70",
        )
        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_processed_articles([first])
            repository.upsert_processed_articles([automatic])
            stored = session.query(ProcessedArticleModel).one()

        self.assertEqual(stored.final_score, 40)
        self.assertEqual(stored.status, "processed")
        self.assertEqual(stored.selection_origin, "admin")

    def test_release_admin_selection_uses_raw_article_id_not_integer_primary_key(self):
        from app.db.models import ProcessedArticleModel
        from app.models.domain import ProcessedArticle, ScoreDimensions
        from app.repositories.radar_repository import RadarRepository

        processed = ProcessedArticle(
            raw_article_id="string-raw-id", event_cluster_id=None,
            dimensions=ScoreDimensions(8, 8, 8, 8, 8, 8), base_score=8,
            final_score=80, title_zh="A", one_line_summary="A", summary_zh="A",
            reason_zh="A", action_zh="A", category="industry", tags=[], selected=True,
            status="processed", selection_origin="admin", selection_reason="admin:force_selected",
        )
        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_processed_articles([processed])
            repository.release_admin_selection("string-raw-id")
            stored = session.query(ProcessedArticleModel).one()

        self.assertEqual(stored.selection_origin, "score")
        self.assertIsNone(stored.selection_reason)

    def test_scoring_materializes_hidden_article_and_removes_it_from_drafts(self):
        from datetime import date, timedelta
        from app.repositories.radar_repository import RadarRepository
        from app.services.ai_service import FakeAIProvider
        from app.services.manual_articles import (
            create_submission,
            process_and_materialize_submission,
        )

        with self.Session() as session:
            repository = RadarRepository(session)
            submission = create_submission(
                repository,
                {"editor_document": self._document(), "manual_fields": {"title": "待审核文章"}},
            )
            process_and_materialize_submission(
                repository, submission.id, ai_provider=FakeAIProvider()
            )
            session.commit()
            start = date.today() - timedelta(days=1)
            end = date.today() + timedelta(days=1)
            public_items = repository.get_all_event_items_between(start, end)
            admin_items = repository.get_all_event_items_between(
                start, end, include_hidden=True
            )
            publication_status = submission.publication_status

        self.assertEqual(publication_status, "published")
        self.assertEqual(public_items, [])
        self.assertEqual(len(admin_items), 1)
        self.assertTrue(admin_items[0]["hidden"])
        self.assertEqual(admin_items[0]["main_source"]["id"], "hotai_manual")

    def test_manual_report_append_is_idempotent(self):
        from app.db.models import DailyReportModel
        from app.repositories.radar_repository import RadarRepository
        from app.services.ai_service import FakeAIProvider
        from app.services.manual_articles import create_submission, process_submission, publish_submission

        with self.Session() as session:
            repository = RadarRepository(session)
            submission = create_submission(
                repository,
                {
                    "mode": "editor",
                    "editor_document": self._document(),
                    "selection_mode": "force_selected",
                },
            )
            process_submission(repository, submission.id, ai_provider=FakeAIProvider())
            publish_submission(repository, submission.id)
            report_date = datetime.now(timezone.utc).astimezone().date()
            session.add(
                DailyReportModel(
                    report_date=report_date,
                    title="Report",
                    summary="",
                    sections={},
                    article_count=0,
                    markdown="",
                )
            )
            session.flush()
            first = repository.append_manual_daily_report_entries(report_date)
            second = repository.append_manual_daily_report_entries(report_date)

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)


class ManualRichTextTests(unittest.TestCase):
    def test_document_converts_to_existing_blocks(self):
        from app.services.manual_richtext import document_to_blocks

        blocks, plain = document_to_blocks(ManualArticleServiceTests._document())
        self.assertEqual([block["type"] for block in blocks], ["heading", "paragraph", "image"])
        self.assertIn("<strong>", blocks[1]["html"])
        self.assertIn("AI Agent", plain)

    def test_rejects_unsafe_image_protocol(self):
        from app.services.manual_richtext import RichTextValidationError, document_to_blocks

        with self.assertRaises(RichTextValidationError):
            document_to_blocks({"type": "doc", "content": [{"type": "image", "attrs": {"src": "javascript:alert(1)"}}]})

    def test_accepts_http_links_and_images_from_pasted_articles(self):
        from app.services.manual_richtext import document_to_blocks

        document = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "原文链接",
                            "marks": [
                                {"type": "link", "attrs": {"href": "http://example.com/a"}}
                            ],
                        }
                    ],
                },
                {"type": "image", "attrs": {"src": "http://img.example.com/a.jpg"}},
            ],
        }
        blocks, _plain = document_to_blocks(document)

        self.assertIn('href="http://example.com/a"', blocks[0]["html"])
        self.assertEqual(blocks[1]["url"], "http://img.example.com/a.jpg")

    def test_preserves_safe_text_styles_and_alignment(self):
        from app.services.manual_richtext import document_to_blocks

        document = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "attrs": {"textAlign": "center"},
                    "content": [
                        {
                            "type": "text",
                            "text": "彩色重点",
                            "marks": [
                                {
                                    "type": "textStyle",
                                    "attrs": {"color": "#ef4444", "fontSize": "20px"},
                                },
                                {"type": "highlight", "attrs": {"color": "#fef08a"}},
                                {"type": "underline"},
                            ],
                        }
                    ],
                }
            ],
        }
        blocks, plain = document_to_blocks(document)

        self.assertEqual(blocks[0]["align"], "center")
        self.assertIn("color: #ef4444", blocks[0]["html"])
        self.assertIn("font-size: 20px", blocks[0]["html"])
        self.assertIn("background-color: #fef08a", blocks[0]["html"])
        self.assertIn("<u>", blocks[0]["html"])
        self.assertEqual(plain, "彩色重点")

    def test_rejects_unsafe_inline_style_value(self):
        from app.services.manual_richtext import RichTextValidationError, document_to_blocks

        document = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "unsafe",
                            "marks": [
                                {
                                    "type": "textStyle",
                                    "attrs": {"color": "red; background:url(javascript:x)"},
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        with self.assertRaises(RichTextValidationError):
            document_to_blocks(document)

    def test_html_editor_preserves_safe_styles_and_original_image_url(self):
        from app.services.manual_richtext import normalize_editor_document

        document, blocks, plain = normalize_editor_document(
            {
                "type": "html",
                "html": """
                    <script>alert(1)</script>
                    <h2 style="color: #ef4444; font-size: 24px">原文标题</h2>
                    <p style="text-align:center"><strong>保留样式</strong></p>
                    <img data-src="//cdn.example.com/original.png" onerror="alert(1)">
                """,
            }
        )

        self.assertNotIn("script", document["html"])
        self.assertNotIn("onerror", document["html"])
        self.assertIn("font-size: 24px", blocks[0]["html"])
        self.assertEqual(blocks[1]["align"], "center")
        self.assertEqual(blocks[2]["url"], "https://cdn.example.com/original.png")
        self.assertIn("原文标题", plain)

    def test_html_editor_accepts_common_blog_lazy_image_attributes_and_typography(self):
        from app.services.manual_richtext import normalize_editor_document

        document, blocks, _plain = normalize_editor_document(
            {
                "type": "html",
                "html": """
                    <p style="font-family: serif; letter-spacing: 1px; text-indent: 2em">
                      博客正文
                    </p>
                    <font color="#ef4444" face="Arial">旧式彩色文字</font>
                    <img src="data:image/gif;base64,placeholder"
                         data-actualsrc="https://cdn.example.com/full.png">
                """,
            }
        )

        self.assertIn("font-family: serif", document["html"])
        self.assertIn("letter-spacing: 1px", blocks[0]["html"])
        self.assertIn("text-indent: 2em", blocks[0]["html"])
        self.assertIn('<span style="color: #ef4444; font-family: Arial">', document["html"])
        self.assertEqual(blocks[2]["url"], "https://cdn.example.com/full.png")


class ManualFetcherSecurityTests(unittest.TestCase):
    def test_rejects_localhost_before_network(self):
        from app.services.manual_article_fetcher import ManualFetchError, validate_public_url

        with self.assertRaises(ManualFetchError) as context:
            validate_public_url("http://localhost/admin")
        self.assertEqual(context.exception.code, "blocked_address")

    def test_manual_page_limit_supports_large_publishers_but_keeps_hard_cap(self):
        from app.services.manual_article_fetcher import manual_article_max_response_bytes

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MANUAL_ARTICLE_MAX_RESPONSE_BYTES", None)
            self.assertEqual(manual_article_max_response_bytes(), 8_000_000)
        with patch.dict(
            os.environ,
            {"MANUAL_ARTICLE_MAX_RESPONSE_BYTES": "999999999"},
            clear=False,
        ):
            self.assertEqual(manual_article_max_response_bytes(), 20_000_000)

    def test_wechat_page_uses_open_graph_title_and_js_content(self):
        from app.crawlers.article_content import extract_article_content
        from app.crawlers.sitemap import extract_page_article, main_content_region

        page = """
            <html><head>
              <title></title>
              <meta property="og:title" content="微信文章标题">
            </head><body>
              <div class="toolbar">工具栏内容不应进入正文</div>
              <h1 id="activity-name">微信文章标题</h1>
              <div id="js_content">
                <section><span>这是微信文章的第一段有效正文，包含足够多的文字用于正文区域识别。文章继续介绍产品能力、使用方式、实际案例、技术背景、数据结果以及作者的经验总结，确保正文长度达到真实文章的基本规模。</span></section>
                <section><span>这是第二段正文，用于验证专用正文选择器能够生效。这里继续补充实现细节、适用对象、已知限制、后续规划和读者可以采取的下一步行动，避免短文本被误判为导航卡片。</span></section>
                <section><span>第三段进一步说明文章来源、发布时间、作者观点与引用资料，同时保留标题层级、段落结构和原始图片地址，最终进入统一的文章评分流程。</span></section>
                <img data-src="https://mmbiz.qpic.cn/test.png">
              </div>
            </body></html>
        """
        title, _description = extract_page_article(page)
        region = main_content_region(page, base_url="https://mp.weixin.qq.com/s/test")
        extracted = extract_article_content(
            region,
            base_url="https://mp.weixin.qq.com/s/test",
            title=title,
        )

        self.assertEqual(title, "微信文章标题")
        self.assertNotIn("工具栏", extracted["original_text"])
        self.assertIn("第一段有效正文", extracted["original_text"])
        self.assertEqual(extracted["original_images"][0]["url"], "https://mmbiz.qpic.cn/test.png")


class ManualImageUploadTests(unittest.TestCase):
    def test_upload_extracts_first_src(self):
        from app.services.manual_image_upload import upload_image_to_host

        class Response:
            is_success = True
            def json(self):
                return [{"src": "https://img.suversal.com/file/test.png"}]

        class Client:
            def __init__(self):
                self.kwargs = None
            def post(self, *args, **kwargs):
                self.kwargs = kwargs
                return Response()

        client = Client()
        with patch.dict(os.environ, {"IMAGE_HOST_AUTH_CODE": "secret"}, clear=False):
            src = upload_image_to_host(
                filename="test.png",
                content_type="image/png",
                data=b"\x89PNG\r\n\x1a\nrest",
                client=client,
            )
        self.assertEqual(src, "https://img.suversal.com/file/test.png")
        self.assertEqual(client.kwargs["files"]["file"][0], "test.png")
        self.assertEqual(client.kwargs["params"]["returnFormat"], "full")

    def test_upload_rejects_mime_spoof(self):
        from app.services.manual_image_upload import ImageUploadError, upload_image_to_host

        with self.assertRaises(ImageUploadError) as context:
            upload_image_to_host(
                filename="fake.png", content_type="image/png", data=b"not a png", client=object()
            )
        self.assertEqual(context.exception.status_code, 415)


@unittest.skipIf(create_engine is None or TestClient is None, "API dependencies are unavailable")
class ManualArticleApiTests(unittest.TestCase):
    def setUp(self):
        from app.db.models import Base
        from app.repositories.radar_repository import RadarRepository
        from sqlalchemy.pool import StaticPool

        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session = sessionmaker(self.engine, future=True)()
        self.repository = RadarRepository(self.session)
        self.env = patch.dict(
            os.environ,
            {
                "ADMIN_TOKEN": "secret",
                "ADMIN_MANUAL_ARTICLE_ENABLED": "true",
                "ADMIN_MANUAL_IMAGE_UPLOAD_ENABLED": "true",
            },
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.session.close()

    def _client(self):
        from app.main import create_app

        return TestClient(create_app(report_repository_factory=lambda: self.repository))

    def test_create_and_list_submission(self):
        client = self._client()
        response = client.post(
            "/api/admin/article-submissions",
            headers={"Authorization": "Bearer secret"},
            json={"mode": "editor", "editor_document": ManualArticleServiceTests._document()},
        )
        listed = client.get(
            "/api/admin/article-submissions",
            headers={"Authorization": "Bearer secret"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["items"][0]["id"], response.json()["id"])

    def test_feature_flag_hides_routes(self):
        client = self._client()
        with patch.dict(os.environ, {"ADMIN_MANUAL_ARTICLE_ENABLED": "false"}, clear=False):
            response = client.get(
                "/api/admin/article-submissions",
                headers={"Authorization": "Bearer secret"},
            )
        self.assertEqual(response.status_code, 404)

    def test_image_endpoint_accepts_multipart_without_generic_proxy(self):
        client = self._client()
        with patch(
            "app.services.manual_image_upload.upload_image_to_host",
            return_value="https://img.suversal.com/file/test.png",
        ):
            response = client.post(
                "/api/admin/uploads/images",
                headers={"Authorization": "Bearer secret"},
                files={"file": ("test.png", b"\x89PNG\r\n\x1a\nrest", "image/png")},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["src"], "https://img.suversal.com/file/test.png")

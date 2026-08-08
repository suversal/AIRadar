"""SourcePilot X 推文同步（Phase 4）：仓库 upsert/查询、同步服务、公开端点。"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
except ModuleNotFoundError:  # pragma: no cover - lightweight env may omit SQLAlchemy
    create_engine = None

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover
    TestClient = None


def make_tweet(tweet_id: str, **overrides):
    tweet = {
        "tweet_id": tweet_id,
        "conversation_id": tweet_id,
        "author_handle": "AnthropicAI",
        "author_name": "Anthropic",
        "text": f"tweet {tweet_id}",
        "display_title": f"tweet {tweet_id}",
        "display_text": f"tweet {tweet_id}",
        "created_at": "2026-08-07T10:00:00Z",
        "likes": 10,
        "retweets": 2,
        "views": 100,
        "tweet_type": "original",
        "content_kind": "brief",
        "url": f"https://x.com/AnthropicAI/status/{tweet_id}",
        "external_urls": [],
        "media": [],
    }
    tweet.update(overrides)
    return tweet


@unittest.skipIf(create_engine is None, "SQLAlchemy is not installed in this environment")
class XTweetRepositoryTests(unittest.TestCase):
    def setUp(self):
        from app.db.models import Base

        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, future=True)

    def _repository(self, session):
        from app.repositories.radar_repository import RadarRepository

        return RadarRepository(session)

    def test_upsert_inserts_then_updates_by_tweet_id(self):
        with self.Session() as session:
            repository = self._repository(session)
            result = repository.upsert_x_tweets([make_tweet("1"), make_tweet("2")])
            self.assertEqual((result.inserted, result.updated), (2, 0))

            # 同一条重来：互动数刷新、长文正文后补，都要覆盖旧 payload
            refreshed = make_tweet("1", likes=99, article_markdown="# 全文")
            result = repository.upsert_x_tweets([refreshed])
            self.assertEqual((result.inserted, result.updated), (0, 1))
            session.commit()

            items, total, _ = repository.query_x_tweets()
            self.assertEqual(total, 2)
            stored = next(item for item in items if item["tweet_id"] == "1")
            self.assertEqual(stored["likes"], 99)
            self.assertEqual(stored["article_markdown"], "# 全文")

    def test_upsert_skips_malformed_rows(self):
        with self.Session() as session:
            repository = self._repository(session)
            result = repository.upsert_x_tweets(
                [
                    make_tweet("ok"),
                    make_tweet("", author_handle="x"),  # 缺 id
                    make_tweet("3", author_handle=""),  # 缺作者
                    make_tweet("4", created_at="not-a-date"),
                ]
            )
            self.assertEqual((result.inserted, result.skipped), (1, 3))

    def test_query_filters_by_kind_and_handle_case_insensitive(self):
        with self.Session() as session:
            repository = self._repository(session)
            repository.upsert_x_tweets(
                [
                    make_tweet("1", content_kind="article"),
                    make_tweet("2", content_kind="brief"),
                    make_tweet("3", content_kind="brief", author_handle="OpenAI"),
                ]
            )
            session.commit()

            items, total, _ = repository.query_x_tweets(kind="brief")
            self.assertEqual(total, 2)
            items, total, _ = repository.query_x_tweets(handle="openai")
            self.assertEqual(total, 1)
            self.assertEqual(items[0]["tweet_id"], "3")

    def test_query_orders_by_created_at_desc(self):
        with self.Session() as session:
            repository = self._repository(session)
            repository.upsert_x_tweets(
                [
                    make_tweet("old", created_at="2026-08-01T00:00:00Z"),
                    make_tweet("new", created_at="2026-08-07T00:00:00Z"),
                    make_tweet("mid", created_at="2026-08-04T00:00:00Z"),
                ]
            )
            session.commit()
            items, _, _ = repository.query_x_tweets()
            self.assertEqual([i["tweet_id"] for i in items], ["new", "mid", "old"])

    def test_latest_created_at_is_per_handle_and_tz_aware(self):
        with self.Session() as session:
            repository = self._repository(session)
            self.assertIsNone(repository.latest_x_tweet_created_at("AnthropicAI"))
            repository.upsert_x_tweets(
                [
                    make_tweet("1", created_at="2026-08-05T00:00:00Z"),
                    make_tweet("2", created_at="2026-08-07T00:00:00Z", author_handle="OpenAI"),
                ]
            )
            session.commit()
            latest = repository.latest_x_tweet_created_at("AnthropicAI")
            self.assertIsNotNone(latest.tzinfo)
            self.assertEqual(latest, datetime(2026, 8, 5, tzinfo=timezone.utc))


@unittest.skipIf(create_engine is None, "SQLAlchemy is not installed in this environment")
class SyncServiceTests(unittest.TestCase):
    def setUp(self):
        from app.db.models import Base

        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, future=True)

    def test_syncs_each_handle_and_reports_counts(self):
        from app.repositories.radar_repository import RadarRepository
        from app.services import x_tweets_sync as module

        def fake_fetch(handle, since):
            if handle == "OpenAI":
                return [make_tweet("10", author_handle="OpenAI")]
            return [make_tweet("20"), make_tweet("21")]

        with self.Session() as session:
            repository = RadarRepository(session)
            with patch.object(module, "fetch_handle_tweets", side_effect=fake_fetch):
                report = module.sync_x_tweets(repository, ["OpenAI", "AnthropicAI"], topics=[])
            session.commit()

        self.assertEqual(report["inserted"], 3)
        self.assertEqual(report["handles"]["OpenAI"]["fetched"], 1)
        self.assertEqual(report["handles"]["AnthropicAI"]["inserted"], 2)

    def test_one_handle_failure_does_not_block_others(self):
        from app.repositories.radar_repository import RadarRepository
        from app.services import x_tweets_sync as module

        def fake_fetch(handle, since):
            if handle == "OpenAI":
                raise RuntimeError("UPSTREAM_DOWN")
            return [make_tweet("30")]

        with self.Session() as session:
            repository = RadarRepository(session)
            with patch.object(module, "fetch_handle_tweets", side_effect=fake_fetch):
                report = module.sync_x_tweets(repository, ["OpenAI", "AnthropicAI"], topics=[])
            session.commit()

        self.assertIn("UPSTREAM_DOWN", report["handles"]["OpenAI"]["error"])
        self.assertEqual(report["handles"]["AnthropicAI"]["inserted"], 1)
        self.assertEqual(report["inserted"], 1)

    def test_since_watermark_rewinds_by_margin(self):
        """水位 = 库内最新 - 3 天：互动数与长文正文都是后补的，
        只追最新会永远拿不到这些更新。"""
        from app.repositories.radar_repository import RadarRepository
        from app.services import x_tweets_sync as module

        seen: dict[str, object] = {}

        def fake_fetch(handle, since):
            seen["since"] = since
            return []

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_x_tweets([make_tweet("1", created_at="2026-08-07T00:00:00Z")])
            session.commit()
            with patch.object(module, "fetch_handle_tweets", side_effect=fake_fetch):
                module.sync_x_tweets(repository, ["AnthropicAI"], topics=[])

        self.assertEqual(
            seen["since"],
            datetime(2026, 8, 7, tzinfo=timezone.utc) - timedelta(days=3),
        )

    def test_first_run_has_no_since(self):
        from app.repositories.radar_repository import RadarRepository
        from app.services import x_tweets_sync as module

        seen: dict[str, object] = {"since": "sentinel"}

        def fake_fetch(handle, since):
            seen["since"] = since
            return []

        with self.Session() as session:
            repository = RadarRepository(session)
            with patch.object(module, "fetch_handle_tweets", side_effect=fake_fetch):
                module.sync_x_tweets(repository, ["AnthropicAI"], topics=[])

        self.assertIsNone(seen["since"])


class FetchEnvelopeTests(unittest.TestCase):
    def test_rate_limited_returns_empty_without_raising(self):
        from app.services import x_tweets_sync as module

        envelope = '{"ok": false, "error": {"code": "RATE_LIMITED", "message": "cooling"}, "meta": {}}'
        with patch.object(module, "fetch_url_text", return_value=envelope):
            self.assertEqual(module.fetch_handle_tweets("OpenAI", None), [])

    def test_other_errors_raise(self):
        from app.services import x_tweets_sync as module

        envelope = '{"ok": false, "error": {"code": "UPSTREAM_DOWN", "message": "down"}, "meta": {}}'
        with patch.object(module, "fetch_url_text", return_value=envelope):
            with self.assertRaises(RuntimeError):
                module.fetch_handle_tweets("OpenAI", None)

    def test_since_serialized_as_utc_z(self):
        from app.services import x_tweets_sync as module

        captured: dict[str, str] = {}

        def fake_fetch_url_text(url, **kwargs):
            captured["url"] = url
            return '{"ok": true, "data": {"tweets": []}, "meta": {}}'

        with patch.object(module, "fetch_url_text", side_effect=fake_fetch_url_text):
            module.fetch_handle_tweets(
                "OpenAI", datetime(2026, 8, 4, 12, 30, tzinfo=timezone.utc)
            )
        self.assertIn("since=2026-08-04T12%3A30%3A00Z", captured["url"])


@unittest.skipIf(create_engine is None, "SQLAlchemy is not installed in this environment")
class TopicSyncTests(unittest.TestCase):
    """SP 契约 §5.5 话题订阅：AR 侧的第二条同步腿。"""

    def setUp(self):
        from app.db.models import Base

        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, future=True)

    def test_upsert_extracts_topics_and_query_filters(self):
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_x_tweets(
                [
                    make_tweet("1", topics=["gpt-5.6"], author_handle="rando1"),
                    make_tweet("2", topics=["gpt-5.6", "claude-fable-5"], author_handle="rando2"),
                    make_tweet("3"),  # 无话题（订阅账号时间线来的）
                ]
            )
            session.commit()

            items, total, _ = repository.query_x_tweets(topic="gpt-5.6")
            self.assertEqual(total, 2)
            items, total, _ = repository.query_x_tweets(topic="claude-fable-5")
            self.assertEqual([i["tweet_id"] for i in items], ["2"])
            # 话题标识是子串也不误中（包裹逗号格式的意义）
            _, total, _ = repository.query_x_tweets(topic="gpt-5")
            self.assertEqual(total, 0)
            self.assertEqual(
                repository.list_x_tweet_topics(), ["claude-fable-5", "gpt-5.6"]
            )

    def test_topic_watermark_is_per_topic(self):
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            self.assertIsNone(repository.latest_x_tweet_created_at(topic="gpt-5.6"))
            repository.upsert_x_tweets(
                [
                    make_tweet("1", topics=["gpt-5.6"], created_at="2026-08-05T00:00:00Z"),
                    make_tweet("2", created_at="2026-08-07T00:00:00Z"),
                ]
            )
            session.commit()
            self.assertEqual(
                repository.latest_x_tweet_created_at(topic="gpt-5.6"),
                datetime(2026, 8, 5, tzinfo=timezone.utc),
            )

    def test_sync_pulls_topics_alongside_handles(self):
        from app.repositories.radar_repository import RadarRepository
        from app.services import x_tweets_sync as module

        def fake_handle_fetch(handle, since):
            return [make_tweet("h1")]

        def fake_topic_fetch(topic, since):
            return [make_tweet("t1", topics=[topic], author_handle="rando")]

        with self.Session() as session:
            repository = RadarRepository(session)
            with patch.object(module, "fetch_handle_tweets", side_effect=fake_handle_fetch), \
                 patch.object(module, "fetch_topic_tweets", side_effect=fake_topic_fetch):
                report = module.sync_x_tweets(
                    repository, ["OpenAI"], topics=["gpt-5.6"]
                )
            session.commit()

        self.assertEqual(report["inserted"], 2)
        self.assertEqual(report["topics"]["gpt-5.6"]["inserted"], 1)

    def test_topic_failure_does_not_block_handles(self):
        from app.repositories.radar_repository import RadarRepository
        from app.services import x_tweets_sync as module

        def fake_topic_fetch(topic, since):
            raise RuntimeError("UPSTREAM_DOWN")

        with self.Session() as session:
            repository = RadarRepository(session)
            with patch.object(module, "fetch_handle_tweets", return_value=[make_tweet("h1")]), \
                 patch.object(module, "fetch_topic_tweets", side_effect=fake_topic_fetch):
                report = module.sync_x_tweets(repository, ["OpenAI"], topics=["gpt-5.6"])
            session.commit()

        self.assertEqual(report["handles"]["OpenAI"]["inserted"], 1)
        self.assertIn("UPSTREAM_DOWN", report["topics"]["gpt-5.6"]["error"])


@unittest.skipIf(create_engine is None, "SQLAlchemy is not installed in this environment")
class TranslationTests(unittest.TestCase):
    def setUp(self):
        from app.db.models import Base

        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, future=True)

    def _provider(self):
        class Provider:
            model = "test-model"

            def translate_paragraphs(self, paragraphs):
                return [f"中文：{p}" for p in paragraphs]

        return Provider()

    def test_translates_new_tweets_and_marks_chinese_as_skipped(self):
        from app.repositories.radar_repository import RadarRepository
        from app.services.x_tweets_translate import translate_x_tweets

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_x_tweets(
                [
                    make_tweet("en", display_text="Hello world"),
                    make_tweet("zh", display_text="这是一条中文推文，不需要翻译的那种。"),
                ]
            )
            session.commit()
            report = translate_x_tweets(repository, self._provider())
            session.commit()

            self.assertEqual(report["translated"], 1)
            self.assertEqual(report["skipped_zh"], 1)
            items, _, _ = repository.query_x_tweets()
            by_id = {i["tweet_id"]: i for i in items}
            self.assertEqual(by_id["en"]["translation"]["display_text_zh"], "中文：Hello world")
            self.assertIsNone(by_id["zh"]["translation"])  # skipped 不透出

    def test_retranslates_when_source_text_changes(self):
        """长文正文后补会改写 display_text——hash 变了必须重翻。"""
        from app.repositories.radar_repository import RadarRepository
        from app.services.x_tweets_translate import translate_x_tweets

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_x_tweets([make_tweet("1", display_text="entry line")])
            session.commit()
            translate_x_tweets(repository, self._provider())
            session.commit()

            # 同步刷新把正文换成了整篇长文
            repository.upsert_x_tweets(
                [make_tweet("1", display_text="# Full article\n\nmany words")]
            )
            session.commit()
            report = translate_x_tweets(repository, self._provider())
            session.commit()
            self.assertEqual(report["translated"], 1)

            # 原文没再变，第三轮不重翻
            report = translate_x_tweets(repository, self._provider())
            self.assertEqual(report["translated"], 0)

    def test_markup_only_paragraphs_bypass_the_model(self):
        from app.repositories.radar_repository import RadarRepository
        from app.services.x_tweets_translate import translate_x_tweets

        text = "Look at this\n\n![](https://pbs.twimg.com/media/a.jpg)\n\nAmazing result"
        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_x_tweets([make_tweet("1", display_text=text)])
            session.commit()
            translate_x_tweets(repository, self._provider())
            session.commit()
            items, _, _ = repository.query_x_tweets()
            zh = items[0]["translation"]["display_text_zh"]
            # 图片段原样保留（没有被模型碰过），文本段翻了
            self.assertIn("![](https://pbs.twimg.com/media/a.jpg)", zh)
            self.assertIn("中文：Look at this", zh)
            self.assertIn("中文：Amazing result", zh)

    def test_translation_survives_payload_refresh(self):
        """同步覆盖 payload 时译文列不能被冲掉（除非原文真变了）。"""
        from app.repositories.radar_repository import RadarRepository
        from app.services.x_tweets_translate import translate_x_tweets

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_x_tweets([make_tweet("1", display_text="Hello", likes=1)])
            session.commit()
            translate_x_tweets(repository, self._provider())
            session.commit()

            # 互动数刷新，正文没变
            repository.upsert_x_tweets([make_tweet("1", display_text="Hello", likes=99)])
            session.commit()
            items, _, _ = repository.query_x_tweets()
            self.assertEqual(items[0]["likes"], 99)
            self.assertEqual(items[0]["translation"]["display_text_zh"], "中文：Hello")


@unittest.skipIf(
    TestClient is None or create_engine is None,
    "FastAPI/SQLAlchemy is not installed in this environment",
)
class PublicTweetsRouteTests(unittest.TestCase):
    def _client(self):
        from sqlalchemy.pool import StaticPool

        from app import main as module
        from app.db.models import Base
        from app.repositories.radar_repository import RadarRepository

        # TestClient 在工作线程里执行同步端点；内存 SQLite 默认按线程给
        # 新连接（= 空库），StaticPool 固定单连接才能看到建的表
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        Session = sessionmaker(engine, future=True)
        self.session = Session()
        repository = RadarRepository(self.session)
        app = module.create_app(report_repository_factory=lambda: repository)
        return TestClient(app), repository

    def test_returns_tweets_with_paging_metadata(self):
        client, repository = self._client()
        repository.upsert_x_tweets(
            [make_tweet("1"), make_tweet("2", content_kind="article")]
        )
        self.session.commit()

        response = client.get("/api/public/tweets")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["item_count"], 2)

        response = client.get("/api/public/tweets", params={"kind": "article"})
        self.assertEqual(response.json()["total"], 1)

    def test_detail_route_returns_single_tweet_or_404(self):
        client, repository = self._client()
        repository.upsert_x_tweets([make_tweet("42", article_markdown="# 全文")])
        self.session.commit()

        response = client.get("/api/public/tweets/42")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["item"]["article_markdown"], "# 全文")
        self.assertEqual(client.get("/api/public/tweets/nope").status_code, 404)

    def test_rejects_unknown_kind_and_bad_paging(self):
        client, _ = self._client()
        self.assertEqual(
            client.get("/api/public/tweets", params={"kind": "nope"}).status_code, 400
        )
        self.assertEqual(
            client.get("/api/public/tweets", params={"limit": 0}).status_code, 400
        )
        self.assertEqual(
            client.get("/api/public/tweets", params={"offset": -1}).status_code, 400
        )


if __name__ == "__main__":
    unittest.main()

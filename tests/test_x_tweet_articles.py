import sys
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
except ModuleNotFoundError:  # pragma: no cover
    create_engine = None

from app.models.domain import Source
from app.pipeline.runner import _terminal_cache_is_current, dedupe_articles, run_pipeline
from app.services.ai_service import FakeAIProvider
from app.services.clustering_service import cluster_articles
from app.services.x_tweet_articles import (
    X_TWEET_ACCOUNT_SOURCE_ID,
    X_TWEET_TOPIC_SOURCE_ID,
    display_source_profile,
    pipeline_source_id_for_tweet,
    load_x_tweet_articles,
    tweet_content_hash,
    tweet_to_raw_article,
)


def make_source(source_id: str = X_TWEET_ACCOUNT_SOURCE_ID) -> Source:
    return Source(
        id=source_id,
        name="X 推文",
        source_role="signal",
        tier="T2" if source_id == X_TWEET_ACCOUNT_SOURCE_ID else "T3",
        type="internal",
        category="community",
        url="internal://x/test",
        homepage="https://x.com",
        allowed_domains=["x.com"],
        is_active=False,
        config={"internal_only": True, "recent_days": 7},
    )


def make_tweet(tweet_id: str, **overrides):
    tweet = {
        "tweet_id": tweet_id,
        "conversation_id": tweet_id,
        "author_handle": "OpenAI",
        "author_name": "OpenAI",
        "author_avatar": "https://pbs.twimg.com/profile_images/openai.jpg",
        "display_title": "A new AI model",
        "display_text": "A new AI model is available for developers.",
        "created_at": "2026-08-29T02:00:00Z",
        "likes": 10,
        "retweets": 2,
        "replies": 1,
        "views": 100,
        "tweet_type": "original",
        "content_kind": "brief",
        "url": f"https://x.com/OpenAI/status/{tweet_id}",
        "topics": [],
        "external_urls": [],
        "media": [],
        "lang": "en",
    }
    tweet.update(overrides)
    return tweet


class XTweetEligibilityTests(unittest.TestCase):
    def test_only_originals_from_subscribed_accounts_or_ai_topic_are_eligible(self):
        handles = {"openai"}
        self.assertEqual(
            pipeline_source_id_for_tweet(make_tweet("1"), handles),
            X_TWEET_ACCOUNT_SOURCE_ID,
        )
        self.assertEqual(
            pipeline_source_id_for_tweet(
                make_tweet("2", author_handle="researcher", topics=["AI热点"]),
                handles,
            ),
            X_TWEET_TOPIC_SOURCE_ID,
        )
        self.assertIsNone(
            pipeline_source_id_for_tweet(
                make_tweet("3", author_handle="seller", topics=["U卡推荐"]),
                handles,
            )
        )
        for tweet_type in ("quote", "reply", "repost"):
            self.assertIsNone(
                pipeline_source_id_for_tweet(
                    make_tweet("4", tweet_type=tweet_type, topics=["AI热点"]),
                    handles,
                )
            )

    def test_content_hash_ignores_engagement_but_tracks_semantic_updates(self):
        original = make_tweet("1")
        self.assertEqual(
            tweet_content_hash(original),
            tweet_content_hash(
                make_tweet("1", likes=999, retweets=500, replies=80, views=99999)
            ),
        )
        self.assertNotEqual(
            tweet_content_hash(original),
            tweet_content_hash(make_tweet("1", article_markdown="# Full article")),
        )
        self.assertNotEqual(
            tweet_content_hash(original),
            tweet_content_hash(
                make_tweet("1", media=[{"type": "image", "url": "https://img/a.jpg"}])
            ),
        )

    def test_converter_preserves_links_and_structured_media(self):
        tweet = make_tweet(
            "42",
            article_markdown=(
                "# Model release\n\nRead the [documentation](https://example.com/docs).\n\n"
                "![model](https://img.example/model.jpg)"
            ),
            external_urls=["https://example.com/docs"],
            media=[
                {
                    "type": "image",
                    "url": "https://img.example/duplicate.jpg",
                    "width": 1200,
                    "height": 800,
                }
            ],
        )
        article = tweet_to_raw_article(tweet, make_source())

        self.assertEqual(article.author, "@openai")
        self.assertEqual(article.source_url, "https://x.com/OpenAI/status/42")
        self.assertEqual(article.metadata["x_author_name"], "OpenAI")
        self.assertEqual(
            article.metadata["x_author_avatar"],
            "https://pbs.twimg.com/profile_images/openai.jpg",
        )
        self.assertEqual(
            display_source_profile(article.metadata),
            {
                "display_name": "OpenAI",
                "handle": "@openai",
                "avatar_url": "https://pbs.twimg.com/profile_images/openai.jpg",
            },
        )
        self.assertIn("Read the documentation.", article.content)
        blocks = article.metadata["original_blocks"]
        self.assertTrue(any(block.get("type") == "heading" for block in blocks))
        self.assertTrue(any(block.get("type") == "image" for block in blocks))
        self.assertTrue(any(block.get("type") == "source_list" for block in blocks))
        self.assertFalse(any("duplicate.jpg" in str(block) for block in blocks))

    def test_x_articles_dedupe_by_status_url_not_generic_title(self):
        first = tweet_to_raw_article(make_tweet("1"), make_source())
        second = tweet_to_raw_article(make_tweet("2"), make_source())
        self.assertEqual(first.title_hash, second.title_hash)
        self.assertEqual(dedupe_articles([first, second]), [first, second])

    def test_changed_x_content_invalidates_terminal_cache(self):
        article = tweet_to_raw_article(make_tweet("1"), make_source())
        cached = {
            "scoring": {"ai_focus": "primary"},
            "metadata": {
                "source_type": "x_tweet",
                "x_content_hash": article.metadata["x_content_hash"],
            },
        }
        self.assertTrue(_terminal_cache_is_current(article, cached))
        changed = replace(article, metadata={**article.metadata, "x_content_hash": "changed"})
        self.assertFalse(_terminal_cache_is_current(changed, cached))

    def test_changed_x_content_is_actually_rescored(self):
        source = make_source()
        article = tweet_to_raw_article(
            make_tweet(
                "1",
                display_title="Updated AI model",
                display_text="Updated AI model adds agent capabilities for developers.",
            ),
            source,
        )
        cached = {
            article.url_hash: {
                "raw_article_id": "persisted-x-id",
                "scoring": {
                    "ai_focus": "primary",
                    "dimensions": {"impact": 1, "novelty": 1, "substance": 1},
                    "category": "industry",
                    "tags": ["old"],
                    "title_zh": "旧标题",
                    "one_line_summary": "旧摘要",
                    "summary_zh": "旧摘要",
                    "reason_zh": "旧理由",
                    "action_zh": "旧动作",
                },
                "metadata": {
                    "source_type": "x_tweet",
                    "x_content_hash": "old-content-hash",
                },
            }
        }

        class CountingProvider(FakeAIProvider):
            def __init__(self):
                self.prefilter_calls = 0
                self.score_calls = 0

            def prefilter(self, text):
                self.prefilter_calls += 1
                return super().prefilter(text)

            def score_article(self, title, content):
                self.score_calls += 1
                return super().score_article(title, content)

        provider = CountingProvider()
        result = run_pipeline(
            sources=[source],
            raw_items_by_source={
                source.id: [
                    {
                        "source_url": article.source_url,
                        "title": article.title,
                        "content": article.content,
                        "author": article.author,
                        "published_at": article.published_at,
                        "language": article.language,
                        "raw_score": article.raw_score,
                        "metadata": article.metadata,
                    }
                ]
            },
            ai_provider=provider,
            now=datetime(2026, 8, 29, 4, tzinfo=timezone.utc),
            report_date=datetime(2026, 8, 29, tzinfo=timezone.utc).date(),
            cached_results=cached,
        )

        self.assertEqual(provider.prefilter_calls, 1)
        self.assertEqual(provider.score_calls, 1)
        self.assertEqual(result.raw_articles[0].id, "persisted-x-id")
        self.assertNotEqual(result.processed_articles[0].title_zh, "旧标题")

    def test_cluster_source_count_uses_distinct_x_authors(self):
        first = tweet_to_raw_article(make_tweet("1"), make_source())
        second = tweet_to_raw_article(
            make_tweet(
                "2",
                author_handle="AnthropicAI",
                url="https://x.com/AnthropicAI/status/2",
            ),
            make_source(),
        )
        same_author = tweet_to_raw_article(make_tweet("3"), make_source())
        clusters = cluster_articles(
            [first, second, same_author],
            {article.id: [1.0, 0.0] for article in (first, second, same_author)},
            threshold=0.9,
        )
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].source_count, 2)


@unittest.skipIf(create_engine is None, "SQLAlchemy is not installed")
class XTweetPipelineRepositoryTests(unittest.TestCase):
    def setUp(self):
        from app.db.models import Base

        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, future=True)

    def test_new_rows_are_opted_in_without_backfilling_existing_rows(self):
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_x_tweets([make_tweet("old")])
            repository.upsert_x_tweets(
                [make_tweet("old", likes=99)],
                article_pipeline_sources={"old": X_TWEET_ACCOUNT_SOURCE_ID},
            )
            repository.upsert_x_tweets(
                [make_tweet("new")],
                article_pipeline_sources={"new": X_TWEET_ACCOUNT_SOURCE_ID},
            )
            session.commit()

            rows = repository.x_tweets_for_article_pipeline(
                since=datetime(2026, 8, 28, tzinfo=timezone.utc),
                limit=10,
            )

        self.assertEqual([row["tweet_id"] for row in rows], ["new"])
        self.assertEqual(
            rows[0]["article_pipeline_source_id"], X_TWEET_ACCOUNT_SOURCE_ID
        )

    def test_loader_converts_database_mirrors_without_fetching(self):
        from app.repositories.radar_repository import RadarRepository

        with self.Session() as session:
            repository = RadarRepository(session)
            repository.upsert_x_tweets(
                [make_tweet("account"), make_tweet("topic", author_handle="researcher")],
                article_pipeline_sources={
                    "account": X_TWEET_ACCOUNT_SOURCE_ID,
                    "topic": X_TWEET_TOPIC_SOURCE_ID,
                },
            )
            session.commit()
            articles, report = load_x_tweet_articles(
                repository,
                [make_source(), make_source(X_TWEET_TOPIC_SOURCE_ID)],
                now=datetime(2026, 8, 29, 4, tzinfo=timezone.utc),
            )

        self.assertEqual({article.source_id for article in articles}, {
            X_TWEET_ACCOUNT_SOURCE_ID,
            X_TWEET_TOPIC_SOURCE_ID,
        })
        self.assertEqual(report["candidates"], 2)
        self.assertEqual(report["converted"], 2)
        self.assertEqual(report["failed"], 0)

    def test_sync_marks_only_v1_eligible_rows(self):
        from app.repositories.radar_repository import RadarRepository
        from app.services import x_tweets_sync

        handle_rows = [
            make_tweet("original"),
            make_tweet("quote", tweet_type="quote"),
            make_tweet("reply", tweet_type="reply"),
            make_tweet("repost", tweet_type="repost"),
        ]

        def topic_rows(topic, since):
            if topic == "AI热点":
                return [make_tweet("topic", author_handle="researcher", topics=[topic])]
            return [make_tweet("sim", author_handle="seller", topics=[topic])]

        with self.Session() as session:
            repository = RadarRepository(session)
            with patch.object(
                x_tweets_sync, "fetch_handle_tweets", return_value=handle_rows
            ), patch.object(
                x_tweets_sync, "fetch_topic_tweets", side_effect=topic_rows
            ):
                x_tweets_sync.sync_x_tweets(
                    repository,
                    handles=["OpenAI"],
                    topics=["AI热点", "U卡推荐"],
                )
            session.commit()
            rows = repository.x_tweets_for_article_pipeline(
                since=datetime(2026, 8, 28, tzinfo=timezone.utc),
                limit=20,
            )

        self.assertEqual({row["tweet_id"] for row in rows}, {"original", "topic"})

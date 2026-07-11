import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

try:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
except ModuleNotFoundError:  # pragma: no cover
    create_engine = None

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "repair_legacy_data.py"
SPEC = importlib.util.spec_from_file_location("repair_legacy_data", SCRIPT_PATH)
repair_legacy_data = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair_legacy_data)


class FakeEmbedder:
    model_name = "BAAI/bge-small-zh-v1.5"

    def embed_text(self, text: str, dimensions: int = 512) -> list[float]:
        return [0.5] * 512


@unittest.skipIf(create_engine is None, "SQLAlchemy is not installed in this environment")
class RepairLegacyDataTests(unittest.TestCase):
    def setUp(self):
        from app.db.models import Base

        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, future=True)

    def _seed_event(self, session, *, drift_link=True):
        from app.models.domain import RawArticle, Source
        from app.repositories.radar_repository import RadarRepository
        from app.db.models import ProcessedArticleModel

        repository = RadarRepository(session)
        repository.upsert_sources(
            [
                Source(
                    id="openai_blog",
                    name="OpenAI Blog",
                    source_role="authority",
                    tier="T1",
                    type="rss",
                    category="official",
                    url="https://openai.com/rss.xml",
                    homepage="https://openai.com",
                    allowed_domains=["openai.com"],
                    config={},
                )
            ]
        )
        repository.upsert_raw_articles(
            [
                RawArticle(
                    id="a1",
                    source_id="openai_blog",
                    source_name="OpenAI Blog",
                    source_role="authority",
                    source_tier="T1",
                    source_url="https://openai.com/a1",
                    title="OpenAI releases agent model",
                    content="AI model release",
                    author=None,
                    published_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
                    language="en",
                    raw_score={},
                    metadata={},
                    title_hash="t-a1",
                    url_hash="u-a1",
                )
            ]
        )
        from app.models.domain import EventCluster, ProcessedArticle, ScoreDimensions

        processed = ProcessedArticle(
            raw_article_id="a1",
            event_cluster_id="e-1",
            dimensions=ScoreDimensions(9, 8, 8, 7, 7, 6),
            base_score=7.8,
            final_score=88.0,
            title_zh="中文标题",
            one_line_summary="一句话",
            summary_zh="摘要",
            reason_zh="理由",
            action_zh="动作",
            category="model_release",
            tags=["Agent"],
            selected=True,
            status="processed",
        )
        repository.upsert_processed_articles([processed])
        cluster = EventCluster(
            id="e-1",
            main_article_id="a1",
            article_ids=["a1"],
            event_title="OpenAI releases agent model",
            event_summary="摘要",
            category="model_release",
            tags=["Agent"],
            final_score=88.0,
            source_count=1,
            first_seen_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
            last_seen_at=datetime(2026, 7, 1, 9, tzinfo=timezone.utc),
            article_similarities={"a1": 1.0},
        )
        repository.upsert_event_clusters([cluster])
        session.commit()
        if drift_link:
            row = session.scalar(
                select(ProcessedArticleModel).where(ProcessedArticleModel.raw_article_id == "a1")
            )
            row.event_cluster_id = None
            session.commit()
        # 遗留形态的 embedding：unknown 模型名 + 旧哈希
        repository.upsert_article_embedding(
            "a1", embedding_model="unknown", vector=[0.1] * 512, source_hash="stale"
        )
        session.commit()
        return repository

    def test_repair_links_restores_cache_column_from_membership(self):
        from app.db.models import ProcessedArticleModel

        with self.Session() as session:
            self._seed_event(session, drift_link=True)

            fixed = repair_legacy_data.repair_event_links(session)
            session.commit()

            stored = session.scalar(
                select(ProcessedArticleModel).where(ProcessedArticleModel.raw_article_id == "a1")
            )

        self.assertEqual(fixed, 1)
        self.assertEqual(stored.event_cluster_id, "e-1")

    def test_reembed_unknown_writes_real_model_and_fresh_hash(self):
        from app.crawlers.base import stable_hash
        from app.db.models import ArticleEmbeddingModel

        with self.Session() as session:
            self._seed_event(session, drift_link=False)

            fixed = repair_legacy_data.reembed_unknown(session, embedder=FakeEmbedder())
            session.commit()

            stored = session.scalar(
                select(ArticleEmbeddingModel).where(ArticleEmbeddingModel.raw_article_id == "a1")
            )

        self.assertEqual(fixed, 1)
        self.assertEqual(stored.embedding_model, "BAAI/bge-small-zh-v1.5")
        self.assertEqual(
            stored.source_hash,
            stable_hash("OpenAI releases agent model\nAI model release"),
        )

    def test_recount_source_counts_fixes_stale_values(self):
        from app.db.models import EventClusterModel

        with self.Session() as session:
            self._seed_event(session, drift_link=False)
            session.get(EventClusterModel, "e-1").source_count = 99
            session.commit()

            fixed = repair_legacy_data.recount_source_counts(session)
            session.commit()

            stored = session.get(EventClusterModel, "e-1")

        self.assertEqual(fixed, 1)
        self.assertEqual(stored.source_count, 1)

    def test_find_articles_needing_reextraction_detects_duplicated_title(self):
        from app.db.models import RawArticleModel

        with self.Session() as session:
            self._seed_event(session, drift_link=False)
            row = session.get(RawArticleModel, "a1")
            row.raw_metadata = {
                **row.raw_metadata,
                "original_paragraphs": ["OpenAI releases agent model", "Real body text follows."],
                "original_images": [],
            }
            session.commit()

            ids = repair_legacy_data.find_articles_needing_reextraction(session)

        self.assertEqual(ids, ["a1"])

    def test_find_articles_needing_reextraction_detects_avatar_image(self):
        from app.db.models import RawArticleModel

        with self.Session() as session:
            self._seed_event(session, drift_link=False)
            row = session.get(RawArticleModel, "a1")
            row.raw_metadata = {
                **row.raw_metadata,
                "original_paragraphs": ["Body text, not the title at all."],
                "original_images": [{"url": "https://example.com/resources/avatar_jane.jpg", "alt": "Jane"}],
            }
            session.commit()

            ids = repair_legacy_data.find_articles_needing_reextraction(session)

        self.assertEqual(ids, ["a1"])

    def test_find_articles_needing_reextraction_ignores_clean_rows(self):
        from app.db.models import RawArticleModel

        with self.Session() as session:
            self._seed_event(session, drift_link=False)
            row = session.get(RawArticleModel, "a1")
            row.raw_metadata = {
                **row.raw_metadata,
                "original_paragraphs": ["Totally unrelated body text."],
                "original_images": [{"url": "https://example.com/hero.png", "alt": "Hero"}],
            }
            session.commit()

            ids = repair_legacy_data.find_articles_needing_reextraction(session)

        self.assertEqual(ids, [])

    def test_reextract_article_content_updates_row_and_translation(self):
        from app.db.models import ArticleTranslationModel, RawArticleModel
        from app.crawlers.base import stable_hash

        with self.Session() as session:
            self._seed_event(session, drift_link=False)
            row = session.get(RawArticleModel, "a1")
            row.raw_metadata = {
                **row.raw_metadata,
                "original_paragraphs": ["OpenAI releases agent model", "Real body text follows."],
                "original_images": [],
            }
            session.add(
                ArticleTranslationModel(
                    raw_article_id="a1",
                    translated_paragraphs=["OpenAI 发布智能体模型", "真正的正文在这里。"],
                    translated_blocks=[],
                    source_language="en",
                    target_language="zh",
                    source_hash="stale-hash",
                    status="completed",
                )
            )
            session.commit()

            payload = {
                "title": "OpenAI releases agent model",
                "content": "Real body text follows.",
                "metadata": {
                    "original_paragraphs": ["Real body text follows."],
                    "original_images": [],
                    "original_blocks": [{"type": "paragraph", "text": "Real body text follows."}],
                },
            }
            fixed = repair_legacy_data.reextract_article_content(
                session,
                "a1",
                fetch_payload=lambda url: payload,
                translate=lambda paragraphs: [f"译:{p}" for p in paragraphs],
            )
            session.commit()

            stored = session.get(RawArticleModel, "a1")
            translation = session.scalar(
                select(ArticleTranslationModel).where(ArticleTranslationModel.raw_article_id == "a1")
            )

        self.assertTrue(fixed)
        self.assertEqual(stored.content, "Real body text follows.")
        self.assertEqual(stored.raw_metadata["original_paragraphs"], ["Real body text follows."])
        self.assertEqual(translation.translated_paragraphs, ["译:Real body text follows."])
        self.assertEqual(translation.source_hash, stable_hash("Real body text follows."))


if __name__ == "__main__":
    unittest.main()

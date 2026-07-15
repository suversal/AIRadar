import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.models.domain import RawArticle, Source
from app.services.clustering_service import (
    canonical_reference_key,
    choose_main_article,
    cluster_articles,
    cosine_similarity,
)


def raw_article(article_id, source_id, role, tier, title, published_hour):
    return RawArticle(
        id=article_id,
        source_id=source_id,
        source_name=source_id,
        source_role=role,
        source_tier=tier,
        source_url=f"https://example.com/{article_id}",
        title=title,
        content=f"{title} content about AI agents and models.",
        author=None,
        published_at=datetime(2026, 7, 1, published_hour, tzinfo=timezone.utc),
        language="en",
        raw_score={},
        metadata={},
        title_hash=f"title-{article_id}",
        url_hash=f"url-{article_id}",
    )


class ClusteringTests(unittest.TestCase):
    def test_cosine_similarity_detects_close_vectors(self):
        self.assertAlmostEqual(cosine_similarity([1, 0, 0], [1, 0, 0]), 1.0)
        self.assertAlmostEqual(cosine_similarity([1, 0, 0], [0, 1, 0]), 0.0)

    def test_cluster_articles_merges_similar_articles(self):
        articles = [
            raw_article("a1", "openai_blog", "authority", "T1", "OpenAI releases agent model", 8),
            raw_article("a2", "hn", "signal", "T2", "OpenAI agent model discussion", 9),
            raw_article("a3", "arxiv", "authority", "T1", "New diffusion paper", 10),
        ]
        embeddings = {
            "a1": [1.0, 0.0, 0.0],
            "a2": [0.97, 0.03, 0.0],
            "a3": [0.0, 1.0, 0.0],
        }

        clusters = cluster_articles(articles, embeddings, threshold=0.85)

        self.assertEqual(len(clusters), 2)
        self.assertEqual(clusters[0].source_count, 2)

    def test_cluster_articles_records_member_similarities(self):
        # 聚类时算出的相似度是判定"这两篇是同一事件"的证据，必须随
        # cluster 输出以便落库——否则无法事后解释误合并或阈值边界
        articles = [
            raw_article("a1", "openai_blog", "authority", "T1", "OpenAI releases agent model", 8),
            raw_article("a2", "hn", "signal", "T2", "OpenAI agent model discussion", 9),
        ]
        embeddings = {
            "a1": [1.0, 0.0, 0.0],
            "a2": [0.97, 0.03, 0.0],
        }

        clusters = cluster_articles(articles, embeddings, threshold=0.85)

        self.assertEqual(len(clusters), 1)
        similarities = clusters[0].article_similarities
        self.assertAlmostEqual(similarities["a1"], 1.0)
        self.assertAlmostEqual(
            similarities["a2"], cosine_similarity([1.0, 0.0, 0.0], [0.97, 0.03, 0.0])
        )

    def test_cluster_articles_merges_exact_cited_source_below_vector_threshold(self):
        articles = [
            raw_article("a1", "telegram_a", "aggregator", "T3", "马斯克宣布开源 X", 8),
            raw_article("a2", "telegram_b", "aggregator", "T3", "X 整个代码库将开源", 9),
        ]
        articles[0].metadata["original_blocks"] = [
            {
                "type": "source_list",
                "links": [
                    {"url": "https://x.com/elonmusk/status/2077361679034118271"}
                ],
            }
        ]
        articles[1].metadata["original_blocks"] = [
            {
                "type": "source_list",
                "links": [{"url": "https://x.com/i/status/2077361679034118271"}],
            }
        ]
        embeddings = {
            "a1": [1.0, 0.0, 0.0],
            "a2": [0.0, 1.0, 0.0],
        }

        clusters = cluster_articles(articles, embeddings, threshold=0.93)

        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].source_count, 2)
        self.assertAlmostEqual(clusters[0].article_similarities["a2"], 0.0)

    def test_reference_key_ignores_homepages_and_normalizes_tracking(self):
        self.assertIsNone(canonical_reference_key("https://example.com/"))
        self.assertEqual(
            canonical_reference_key("https://example.com/news/42?utm_source=rss&id=7"),
            "url:example.com/news/42?id=7",
        )

    def test_cluster_ids_are_stable_across_runs_and_orderings(self):
        articles = [
            raw_article("a1", "openai_blog", "authority", "T1", "OpenAI releases agent model", 8),
            raw_article("a2", "hn", "signal", "T2", "OpenAI agent model discussion", 9),
            raw_article("a3", "arxiv", "authority", "T1", "New diffusion paper", 10),
        ]
        embeddings = {
            "a1": [1.0, 0.0, 0.0],
            "a2": [0.97, 0.03, 0.0],
            "a3": [0.0, 1.0, 0.0],
        }

        first_run = cluster_articles(articles, embeddings, threshold=0.85)
        second_run = cluster_articles(list(reversed(articles)), embeddings, threshold=0.85)

        first_ids = {cluster.main_article_id: cluster.id for cluster in first_run}
        second_ids = {cluster.main_article_id: cluster.id for cluster in second_run}
        self.assertEqual(first_ids, second_ids)
        # ids must be content-derived, not positional counters
        self.assertNotIn("c1", first_ids.values())
        for cluster_id in first_ids.values():
            self.assertRegex(cluster_id, r"^e[0-9a-f]{12}$")

    def test_choose_main_article_prefers_authority_over_aggregator(self):
        sources = {
            "openai_blog": Source(
                id="openai_blog",
                name="OpenAI Blog",
                source_role="authority",
                tier="T1",
                type="rss",
                category="official",
                url="https://openai.com/rss.xml",
                homepage="https://openai.com",
                allowed_domains=["openai.com"],
                can_be_main_source=True,
            ),
            "newsnow": Source(
                id="newsnow",
                name="NewsNow",
                source_role="aggregator",
                tier="T3",
                type="aggregator",
                category="aggregator",
                url="https://newsnow.example/rss.xml",
                homepage="https://newsnow.example",
                allowed_domains=["newsnow.example"],
                can_be_main_source=False,
            ),
        }
        authority = raw_article("a1", "openai_blog", "authority", "T1", "Model release", 8)
        aggregator = raw_article("a2", "newsnow", "aggregator", "T3", "Model release mirror", 9)

        main = choose_main_article(
            [aggregator, authority],
            sources=sources,
            final_scores={"a1": 80.0, "a2": 99.0},
        )

        self.assertEqual(main.id, "a1")


if __name__ == "__main__":
    unittest.main()

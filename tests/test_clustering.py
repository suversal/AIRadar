import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.models.domain import RawArticle, Source
from app.services.clustering_service import (
    GRAY_ZONE_FLOOR,
    X_TEXT_RECALL_FLOOR,
    canonical_reference_key,
    centroid,
    choose_main_article,
    cluster_articles,
    cosine_similarity,
    event_text_affinity,
    reference_keys_from_metadata,
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
    def test_x_text_recall_recognizes_paraphrased_processed_titles(self):
        affinity = event_text_affinity(
            "OpenAI宣布因Cursor被SpaceX收购将终止模型供应",
            "OpenAI宣布因Cursor被SpaceX收购将终止模型授权合作",
        )

        self.assertGreaterEqual(affinity, X_TEXT_RECALL_FLOOR)
        self.assertLess(
            event_text_affinity(
                "OpenAI宣布终止向Cursor提供模型",
                "Anthropic发布Claude桌面端新功能",
            ),
            X_TEXT_RECALL_FLOOR,
        )

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

    def test_semantic_match_requires_second_stage_confirmation_when_configured(self):
        articles = [
            raw_article(
                "a1",
                "nvidia",
                "authority",
                "T1",
                "NVIDIA launches an open AI security alliance",
                8,
            ),
            raw_article(
                "a2",
                "techcrunch",
                "signal",
                "T2",
                "Meta expands enterprise AI APIs and compute sales",
                9,
            ),
        ]
        embeddings = {"a1": [1.0, 0.0], "a2": [0.99, 0.01]}
        compared: list[tuple[str, str]] = []

        clusters = cluster_articles(
            articles,
            embeddings,
            threshold=0.90,
            same_event_verifier=lambda left, right: (
                compared.append((left["id"], right["id"])) or False
            ),
        )

        self.assertEqual(len(clusters), 2)
        self.assertEqual(compared, [("a1", "a2")])

    def test_cluster_articles_enforces_maximum_event_time_span(self):
        first = raw_article(
            "a1", "openai_blog", "authority", "T1", "OpenAI releases agent model", 8
        )
        delayed = raw_article(
            "a2", "hn", "signal", "T2", "OpenAI agent model discussion", 9
        )
        delayed.published_at = delayed.published_at.replace(day=2, hour=9)

        clusters = cluster_articles(
            [first, delayed],
            {"a1": [1.0, 0.0], "a2": [0.99, 0.01]},
            threshold=0.90,
            max_event_span_hours=24,
            same_event_verifier=lambda _left, _right: True,
        )

        self.assertEqual(len(clusters), 2)

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

    def test_cluster_articles_matches_official_source_url_to_aggregator_citation(self):
        official = raw_article(
            "a1", "anthropic", "authority", "T1", "Introducing Claude Opus 5", 8
        )
        official.source_url = "https://www.anthropic.com/news/claude-opus-5"
        aggregator = raw_article(
            "a2", "telegram", "aggregator", "T3", "Anthropic 发布 Claude Opus 5", 9
        )
        aggregator.metadata["original_blocks"] = [
            {
                "type": "source_list",
                "links": [
                    {"url": "https://www.anthropic.com/news/claude-opus-5"}
                ],
            }
        ]

        clusters = cluster_articles([official, aggregator], {}, threshold=0.90)

        self.assertEqual(len(clusters), 1)
        self.assertEqual(set(clusters[0].article_ids), {"a1", "a2"})

    def test_cluster_articles_matches_x_status_link_inside_paragraph_html(self):
        original = raw_article(
            "a1", "x_tweet_account", "signal", "T2", "Codex usage reset", 8
        )
        original.source_url = "https://x.com/thsottiaux/status/2093801758665715784"
        telegram = raw_article(
            "a2", "telegram", "aggregator", "T3", "Codex 用量重置", 9
        )
        telegram.metadata["original_blocks"] = [
            {
                "type": "paragraph",
                "text": "Tibo (@thsottiaux)",
                "html": (
                    '<a href="https://x.com/thsottiaux/status/2093801758665715784">'
                    "Tibo (@thsottiaux)</a>"
                ),
            }
        ]

        clusters = cluster_articles(
            [original, telegram],
            {"a1": [1.0, 0.0], "a2": [0.0, 1.0]},
            threshold=0.90,
        )

        self.assertEqual(len(clusters), 1)
        self.assertEqual(set(clusters[0].article_ids), {"a1", "a2"})

    def test_reference_keys_recurse_into_quotes_and_accept_x_embeds(self):
        keys = reference_keys_from_metadata(
            {
                "original_blocks": [
                    {
                        "type": "quote",
                        "kind": "reply",
                        "children": [
                            {
                                "type": "source_list",
                                "links": [{"url": "https://example.com/story/42"}],
                            }
                        ],
                    },
                    {
                        "type": "social_embed",
                        "provider": "x",
                        "url": "https://twitter.com/i/status/2093801758665715784",
                    },
                ]
            }
        )

        self.assertEqual(
            keys,
            {"url:example.com/story/42", "x-status:2093801758665715784"},
        )

    def test_inline_links_ignore_profiles_and_unrelated_articles(self):
        keys = reference_keys_from_metadata(
            {
                "original_blocks": [
                    {
                        "type": "paragraph",
                        "text": "作者与延伸阅读",
                        "html": (
                            '<a href="https://x.com/thsottiaux">作者主页</a>'
                            '<a href="https://example.com/related-story">延伸阅读</a>'
                        ),
                    }
                ]
            }
        )

        self.assertEqual(keys, set())

    def test_cluster_articles_does_not_transitively_chain_unrelated_articles(self):
        # single-linkage regression: the bucket founder (a1, earliest
        # published) individually clears the bar against both a2 and a3, but
        # a2~a3 does not clear it. The old algorithm only ever compared new
        # candidates against the bucket's fixed founding vector, so both a2
        # and a3 would join a1's bucket - even though a2 and a3 themselves
        # are unrelated. This is exactly how a batch of Claude release posts
        # once absorbed unrelated arXiv papers and OpenAI news in production:
        # each new article only had to clear the bar against whichever single
        # vector the bucket already had, never against the whole group.
        articles = [
            raw_article("a1", "openai_blog", "authority", "T1", "Founder article", 8),
            raw_article("a2", "openai_blog", "authority", "T1", "Related to founder", 9),
            raw_article("a3", "openai_blog", "authority", "T1", "Also related to founder only", 10),
        ]
        embeddings = {
            "a1": [1.0, 0.0],
            "a2": [0.866, 0.5],  # cos(a1, a2) ~= 0.866
            "a3": [0.866, -0.5],  # cos(a1, a3) ~= 0.866, cos(a2, a3) = 0.5
        }
        # sanity check the fixture actually represents the intended shape:
        # a1 clears 0.7 against both, but a2 and a3 don't clear it against
        # each other
        self.assertGreaterEqual(cosine_similarity(embeddings["a1"], embeddings["a2"]), 0.7)
        self.assertGreaterEqual(cosine_similarity(embeddings["a1"], embeddings["a3"]), 0.7)
        self.assertLess(cosine_similarity(embeddings["a2"], embeddings["a3"]), 0.7)

        clusters = cluster_articles(articles, embeddings, threshold=0.7)

        # a2 and a3 must never land in the same bucket as each other
        for cluster in clusters:
            self.assertFalse({"a2", "a3"}.issubset(set(cluster.article_ids)))

    def test_cluster_articles_joins_the_best_matching_bucket_not_the_first(self):
        articles = [
            raw_article("a1", "openai_blog", "authority", "T1", "Bucket one seed", 8),
            raw_article("a2", "openai_blog", "authority", "T1", "Bucket two seed", 9),
            raw_article("a3", "openai_blog", "authority", "T1", "Closer to bucket two", 10),
        ]
        embeddings = {
            "a1": [1.0, 0.0, 0.0],
            "a2": [0.0, 1.0, 0.0],
            # qualifies for both buckets, but is a much closer match to a2
            "a3": [0.75, 0.85, 0.0],
        }
        clusters = cluster_articles(articles, embeddings, threshold=0.6)

        by_main = {frozenset(c.article_ids) for c in clusters}
        self.assertIn(frozenset({"a2", "a3"}), by_main)
        self.assertIn(frozenset({"a1"}), by_main)

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


class GrayZoneClusteringTests(unittest.TestCase):
    """2026-08-03 regression: 阿里发布 Qwen3.8-Max was one event reported by 8+
    outlets, and the live 0.90 threshold filed it as 8 separate events. Measured
    on the real embeddings, reports of that single event sat at 0.75-0.88
    against each other - never reaching 0.90 - while 「Qwen3.8-Max 发布」and
    「千问办公公测」, two genuinely different events, sat at 0.837. No threshold
    separates those two cases, so the band below the threshold is decided by the
    same-event verifier instead of by moving the number."""

    #: a1 at 0°, a2 at 10° (their centroid points at 5°), candidate at -25°:
    #: 0.866 against the centroid - inside the band, below the 0.90 threshold -
    #: while its weakest individual link (0.819 against a2) is exactly what
    #: complete-linkage rejected in production.
    BUCKET = {"a1": [1.0, 0.0], "a2": [0.985, 0.174]}
    CANDIDATE = [0.906, -0.423]

    def _articles(self):
        return [
            raw_article("a1", "openai_blog", "authority", "T1", "Alibaba ships Qwen3.8-Max", 8),
            raw_article("a2", "ithome", "signal", "T2", "Qwen3.8-Max is now live", 9),
            raw_article("a3", "infoq", "signal", "T2", "Alibaba releases Qwen3.8 flagship", 10),
        ]

    def _embeddings(self):
        return {**self.BUCKET, "a3": self.CANDIDATE}

    def test_fixture_sits_in_the_gray_band_and_fails_complete_linkage(self):
        # guard the fixture itself: if these numbers drift the two tests below
        # stop testing the band and silently start testing the direct path
        centre = centroid([self.BUCKET["a1"], self.BUCKET["a2"]])
        centre_score = cosine_similarity(self.CANDIDATE, centre)
        self.assertGreaterEqual(centre_score, GRAY_ZONE_FLOOR)
        self.assertLess(centre_score, 0.90)
        weakest = min(
            cosine_similarity(self.CANDIDATE, self.BUCKET["a1"]),
            cosine_similarity(self.CANDIDATE, self.BUCKET["a2"]),
        )
        self.assertLess(weakest, 0.90)

    def test_gray_zone_match_merges_when_the_verifier_confirms(self):
        clusters = cluster_articles(
            self._articles(),
            self._embeddings(),
            threshold=0.90,
            same_event_verifier=lambda _left, _right: True,
        )

        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].source_count, 3)

    def test_gray_zone_match_stays_split_when_the_verifier_rejects(self):
        # 「Qwen3.8-Max 发布」vs「千问办公公测」at 0.837: inside the band, but a
        # different event. The verifier is the only thing that can tell these
        # apart from the merge case above - the vectors cannot. a1/a2 are 0.985
        # apart and merge through the direct path either way, so rejecting only
        # the band comparison isolates what the band itself decides.
        clusters = cluster_articles(
            self._articles(),
            self._embeddings(),
            threshold=0.90,
            same_event_verifier=lambda left, right: "a3" not in (left["id"], right["id"]),
        )

        self.assertEqual(len(clusters), 2)
        by_size = sorted(clusters, key=lambda cluster: len(cluster.article_ids))
        self.assertEqual(by_size[0].article_ids, ["a3"])
        self.assertEqual(sorted(by_size[1].article_ids), ["a1", "a2"])

    def test_gray_zone_asks_the_verifier_about_the_closest_member_only(self):
        # one API call per candidate bucket, not one per member: the closest
        # report carries the judgement, so a3 is compared against a1 (0.906)
        # rather than a2 (0.819). ('a1','a2') is the direct-path check that
        # runs before the band is ever reached.
        compared: list[tuple[str, str]] = []

        cluster_articles(
            self._articles(),
            self._embeddings(),
            threshold=0.90,
            same_event_verifier=lambda left, right: (
                compared.append((left["id"], right["id"])) or True
            ),
        )

        self.assertEqual(compared, [("a1", "a2"), ("a1", "a3")])

    def test_gray_zone_is_skipped_without_a_verifier(self):
        # fail-closed: vector similarity already said it cannot decide, and
        # merging on a guess is what chains unrelated events together
        clusters = cluster_articles(
            self._articles(),
            self._embeddings(),
            threshold=0.90,
        )

        self.assertEqual(len(clusters), 2)

    def test_verified_band_lets_a_correct_bucket_keep_growing(self):
        # the fragmentation mechanism itself: under complete-linkage every
        # article added to a bucket contributes another link that a later report
        # of the same event must clear, so the more coverage an event accumulated
        # the harder it became to join. The band recalls those reports on the
        # centroid and lets the verifier admit them, so a fourth report of the
        # same event still lands in the same bucket.
        articles = [
            *self._articles(),
            raw_article("a4", "qbitai", "signal", "T2", "Qwen3.8-Max hits top tier", 11),
        ]
        embeddings = {**self._embeddings(), "a4": [0.94, -0.34]}

        clusters = cluster_articles(
            articles,
            embeddings,
            threshold=0.90,
            same_event_verifier=lambda _left, _right: True,
        )

        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].source_count, 4)


if __name__ == "__main__":
    unittest.main()

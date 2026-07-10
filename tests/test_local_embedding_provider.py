import math
import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

try:
    import fastembed  # noqa: F401

    FASTEMBED_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - local lightweight env may omit fastembed
    FASTEMBED_AVAILABLE = False


def cosine_similarity(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b)


@unittest.skipIf(not FASTEMBED_AVAILABLE, "fastembed is not installed in this environment")
class LocalEmbeddingProviderTests(unittest.TestCase):
    def test_embed_text_is_deterministic(self):
        from app.services.ai_service import LocalEmbeddingProvider

        provider = LocalEmbeddingProvider()

        first = provider.embed_text("OpenAI 发布了新一代模型")
        second = provider.embed_text("OpenAI 发布了新一代模型")

        self.assertEqual(first, second)

    def test_semantically_similar_chinese_text_scores_higher_than_unrelated_text(self):
        from app.services.ai_service import LocalEmbeddingProvider

        provider = LocalEmbeddingProvider()

        anchor = provider.embed_text("OpenAI 发布了新一代大模型")
        similar = provider.embed_text("OpenAI 推出下一代大模型")
        unrelated = provider.embed_text("今天天气不错，适合出门散步")

        similar_score = cosine_similarity(anchor, similar)
        unrelated_score = cosine_similarity(anchor, unrelated)

        self.assertGreater(similar_score, unrelated_score)
        self.assertGreater(similar_score, 0.7)
        self.assertLess(unrelated_score, 0.6)


if __name__ == "__main__":
    unittest.main()

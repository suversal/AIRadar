import math
import os
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

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
    def setUp(self):
        from app.services.ai_service import LocalEmbeddingProvider

        LocalEmbeddingProvider._model = None
        LocalEmbeddingProvider._model_key = None
        LocalEmbeddingProvider._model_load_error = None

    def tearDown(self):
        from app.services.ai_service import LocalEmbeddingProvider

        LocalEmbeddingProvider._model = None
        LocalEmbeddingProvider._model_key = None
        LocalEmbeddingProvider._model_load_error = None

    def test_uses_configured_stable_cache_directory(self):
        from app.services.ai_service import LocalEmbeddingProvider

        with tempfile.TemporaryDirectory() as cache_dir:
            fake_model = object()
            with (
                patch.dict(os.environ, {"FASTEMBED_CACHE_DIR": cache_dir}),
                patch("fastembed.TextEmbedding", return_value=fake_model) as constructor,
            ):
                provider = LocalEmbeddingProvider()
                self.assertIs(provider._get_model(), fake_model)

            constructor.assert_called_once_with(
                model_name="BAAI/bge-small-zh-v1.5",
                cache_dir=str(Path(cache_dir).resolve()),
            )

    def test_initializes_model_only_once_under_concurrency(self):
        from app.services.ai_service import LocalEmbeddingProvider

        with tempfile.TemporaryDirectory() as cache_dir:
            fake_model = object()

            def construct(**kwargs):
                time.sleep(0.02)
                return fake_model

            with patch("fastembed.TextEmbedding", side_effect=construct) as constructor:
                provider = LocalEmbeddingProvider(cache_dir=cache_dir)
                with ThreadPoolExecutor(max_workers=8) as executor:
                    models = list(executor.map(lambda _: provider._get_model(), range(16)))

            self.assertTrue(all(model is fake_model for model in models))
            constructor.assert_called_once()

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

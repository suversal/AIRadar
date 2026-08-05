import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTE = ROOT / "apps" / "web" / "app" / "api" / "image-proxy" / "route.ts"


class ImageProxyRouteTests(unittest.TestCase):
    def test_octet_stream_is_only_recovered_for_known_image_extensions(self):
        source = ROUTE.read_text(encoding="utf-8")

        self.assertIn('".webp": "image/webp"', source)
        self.assertIn('normalizedType !== "application/octet-stream"', source)
        self.assertIn("pathname.endsWith(extension)", source)
        self.assertIn('"X-Content-Type-Options": "nosniff"', source)
        self.assertIn("if (!upstream.ok || !responseImageType)", source)


if __name__ == "__main__":
    unittest.main()

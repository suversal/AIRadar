import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
except ModuleNotFoundError:  # pragma: no cover - local lightweight env may omit SQLAlchemy
    create_engine = None

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:
    TestClient = None


@unittest.skipIf(create_engine is None or TestClient is None, "SQLAlchemy/FastAPI not installed")
class FeedbackApiTests(unittest.TestCase):
    def setUp(self):
        from app.db.models import Base
        from app.repositories.radar_repository import RadarRepository

        # TestClient runs the request in a worker thread, so the default
        # SingletonThreadPool (one connection tied to the creating thread)
        # would hand that request a fresh, empty :memory: database - pin
        # everyone to the same connection instead.
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, future=True)
        self.session = self.Session()

        from app import main as module

        app = module.create_app(
            report_repository_factory=lambda: RadarRepository(self.session)
        )
        self.client = TestClient(app)
        # never let a test suite run send a real push to the maintainer's
        # Telegram - only assert the endpoint attempts it, not that it lands
        self.telegram_patcher = patch(
            "app.services.telegram_notifier.send_telegram_message", return_value=True
        )
        self.mock_send_telegram = self.telegram_patcher.start()

    def tearDown(self):
        self.telegram_patcher.stop()
        self.session.close()

    def test_submit_feedback_persists_message_and_email(self):
        from app.db.models import FeedbackSubmissionModel

        response = self.client.post(
            "/api/public/feedback",
            json={"message": "希望能加个暗色模式", "email": "user@example.com"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        stored = self.session.query(FeedbackSubmissionModel).one()
        self.assertEqual(stored.message, "希望能加个暗色模式")
        self.assertEqual(stored.email, "user@example.com")
        self.assertTrue(self.mock_send_telegram.called)
        notified_text = self.mock_send_telegram.call_args[0][0]
        self.assertIn("希望能加个暗色模式", notified_text)
        self.assertIn("user@example.com", notified_text)

    def test_submit_feedback_without_email_is_allowed(self):
        from app.db.models import FeedbackSubmissionModel

        response = self.client.post("/api/public/feedback", json={"message": "反馈内容"})

        self.assertEqual(response.status_code, 200)
        stored = self.session.query(FeedbackSubmissionModel).one()
        self.assertIsNone(stored.email)

    def test_submit_feedback_rejects_empty_message(self):
        response = self.client.post("/api/public/feedback", json={"message": "   "})

        self.assertEqual(response.status_code, 422)

    def test_submit_feedback_rejects_overlong_message(self):
        response = self.client.post(
            "/api/public/feedback", json={"message": "x" * 2001}
        )

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()

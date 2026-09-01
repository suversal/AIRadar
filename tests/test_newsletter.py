from __future__ import annotations

import os
import re
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.db.models import (  # noqa: E402
    Base,
    NewsletterDeliveryModel,
    NewsletterSubscriberModel,
    PeriodReportModel,
)
from app.main import create_app  # noqa: E402
from app.repositories.radar_repository import RadarRepository  # noqa: E402
from app.services.newsletter_service import (  # noqa: E402
    NewsletterMessage,
    dispatch_latest_weekly,
    token_hash,
    unsubscribe_token_for,
)


class RecordingMailer:
    def __init__(self):
        self.messages: list[NewsletterMessage] = []

    def send(self, message: NewsletterMessage) -> str:
        self.messages.append(message)
        return f"message-{len(self.messages)}"


class NewsletterTests(unittest.TestCase):
    SECRET = "test-newsletter-secret-with-enough-entropy"

    def setUp(self):
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(engine, expire_on_commit=False)
        self.session = self.Session()
        self.repository = RadarRepository(self.session)
        self.mailer = RecordingMailer()
        self.client = self._client()

    def tearDown(self):
        self.session.close()

    def _client(self):
        from fastapi.testclient import TestClient

        app = create_app(
            report_repository_factory=lambda: self.repository,
            newsletter_mailer=self.mailer,
            newsletter_secret=self.SECRET,
        )
        return TestClient(app)

    def _subscribe_and_confirm(self, email: str = "Reader@Example.com"):
        response = self.client.post(
            "/api/public/newsletter/subscribe",
            json={"email": email, "source": "weekly_page"},
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(self.mailer.messages), 1)
        match = re.search(r"token=([^\s&]+)", self.mailer.messages[0].text)
        self.assertIsNotNone(match)
        token = match.group(1)
        confirmed = self.client.post(
            "/api/public/newsletter/confirm", json={"token": token}
        )
        self.assertEqual(confirmed.status_code, 200)
        return self.session.scalar(select(NewsletterSubscriberModel))

    def test_subscribe_is_double_opt_in_and_normalizes_email(self):
        subscriber = self._subscribe_and_confirm()
        self.assertEqual(subscriber.email, "reader@example.com")
        self.assertEqual(subscriber.status, "active")
        self.assertIsNotNone(subscriber.confirmed_at)
        self.assertNotIn("Reader@Example.com", subscriber.confirmation_token_hash)

    def test_active_address_does_not_receive_repeated_confirmation(self):
        self._subscribe_and_confirm()
        response = self.client.post(
            "/api/public/newsletter/subscribe", json={"email": "reader@example.com"}
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(len(self.mailer.messages), 1)

    def test_invalid_email_is_rejected(self):
        response = self.client.post(
            "/api/public/newsletter/subscribe", json={"email": "not-an-email"}
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.session.query(NewsletterSubscriberModel).count(), 0)

    def test_unsubscribe_is_idempotent(self):
        subscriber = self._subscribe_and_confirm()
        token = unsubscribe_token_for(subscriber.id, self.SECRET)
        first = self.client.post(
            "/api/public/newsletter/unsubscribe", json={"token": token}
        )
        second = self.client.post(
            "/api/public/newsletter/unsubscribe", json={"token": token}
        )
        self.assertEqual(first.json()["status"], "unsubscribed")
        self.assertEqual(second.json()["status"], "already_unsubscribed")
        self.assertEqual(subscriber.status, "unsubscribed")

    def test_dispatch_sends_finalized_issue_once(self):
        finalized_at = datetime(2026, 8, 31, 0, 30, tzinfo=timezone.utc)
        subscriber = NewsletterSubscriberModel(
            id="a" * 32,
            email="reader@example.com",
            status="active",
            confirmation_token_hash=token_hash("confirmation"),
            unsubscribe_token_hash=token_hash(
                unsubscribe_token_for("a" * 32, self.SECRET)
            ),
            confirmation_expires_at=finalized_at,
            confirmation_sent_at=finalized_at - timedelta(days=2),
            confirmed_at=finalized_at - timedelta(days=1),
            source="test",
        )
        report = PeriodReportModel(
            kind="weekly",
            period_key="2026-W35",
            range_start=date(2026, 8, 24),
            range_end=date(2026, 8, 30),
            mainline_title="本周模型入口进一步下沉",
            mainline_body="开发工具与企业调用成为本周主线。",
            theme_notes=[],
            article_count=1,
            report_dates=["2026-08-30"],
            entries=[{"event_id": "event-1", "days_covered": 2}],
            stats={},
            status="generated",
            finalized_at=finalized_at,
        )
        self.session.add_all([subscriber, report])
        self.session.commit()
        self.repository.get_event_items_by_ids = lambda event_ids: [
            {
                "event_id": event_ids[0],
                "title": "测试事件",
                "one_line_summary": "用于验证周报投递。",
                "focus_category_label": "模型与研究",
                "source_count": 2,
            }
        ]

        first = dispatch_latest_weekly(
            self.repository,
            self.mailer,
            now=finalized_at + timedelta(hours=1),
            site_url="https://radar.example",
            token_secret=self.SECRET,
        )
        second = dispatch_latest_weekly(
            self.repository,
            self.mailer,
            now=finalized_at + timedelta(hours=2),
            site_url="https://radar.example",
            token_secret=self.SECRET,
        )

        self.assertEqual(first["sent"], 1)
        self.assertEqual(second["sent"], 0)
        self.assertEqual(len(self.mailer.messages), 1)
        self.assertIn("List-Unsubscribe-Post", self.mailer.messages[0].headers)
        delivery = self.session.scalar(select(NewsletterDeliveryModel))
        self.assertEqual(delivery.status, "sent")
        self.assertEqual(delivery.attempt_count, 1)

    def test_late_subscriber_waits_for_next_issue_unless_admin_forces_latest(self):
        finalized_at = datetime(2026, 8, 31, 0, 30, tzinfo=timezone.utc)
        subscriber = NewsletterSubscriberModel(
            id="b" * 32,
            email="late@example.com",
            status="active",
            confirmation_token_hash=token_hash("late-confirmation"),
            unsubscribe_token_hash=token_hash(
                unsubscribe_token_for("b" * 32, self.SECRET)
            ),
            confirmation_expires_at=finalized_at + timedelta(days=2),
            confirmation_sent_at=finalized_at + timedelta(minutes=1),
            confirmed_at=finalized_at + timedelta(minutes=2),
            source="test",
        )
        report = PeriodReportModel(
            kind="weekly",
            period_key="2026-W35",
            range_start=date(2026, 8, 24),
            range_end=date(2026, 8, 30),
            mainline_title="已封版",
            mainline_body="不补发给封版后才确认的地址。",
            theme_notes=[],
            article_count=0,
            report_dates=[],
            entries=[],
            stats={},
            status="generated",
            finalized_at=finalized_at,
        )
        self.session.add_all([subscriber, report])
        self.session.commit()
        result = dispatch_latest_weekly(
            self.repository,
            self.mailer,
            now=finalized_at + timedelta(hours=1),
            site_url="https://radar.example",
            token_secret=self.SECRET,
        )
        self.assertEqual(result["sent"], 0)
        self.assertEqual(self.mailer.messages, [])

        forced = dispatch_latest_weekly(
            self.repository,
            self.mailer,
            now=finalized_at + timedelta(hours=2),
            site_url="https://radar.example",
            token_secret=self.SECRET,
            include_late_subscribers=True,
        )
        repeated = dispatch_latest_weekly(
            self.repository,
            self.mailer,
            now=finalized_at + timedelta(hours=3),
            site_url="https://radar.example",
            token_secret=self.SECRET,
            include_late_subscribers=True,
        )
        self.assertEqual(forced["sent"], 1)
        self.assertEqual(repeated["sent"], 0)
        self.assertEqual(len(self.mailer.messages), 1)


if __name__ == "__main__":
    unittest.main()

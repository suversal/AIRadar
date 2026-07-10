import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.services.refresh_service import should_trigger_refresh


class ShouldTriggerRefreshTests(unittest.TestCase):
    def test_disabled_never_triggers(self):
        config = {"enabled": False, "interval_minutes": 120, "last_triggered_at": None}
        now = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)

        self.assertFalse(should_trigger_refresh(config, now))

    def test_enabled_and_never_triggered_before_triggers_immediately(self):
        config = {"enabled": True, "interval_minutes": 120, "last_triggered_at": None}
        now = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)

        self.assertTrue(should_trigger_refresh(config, now))

    def test_enabled_but_interval_not_elapsed_does_not_trigger(self):
        last = datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc)
        config = {
            "enabled": True,
            "interval_minutes": 120,
            "last_triggered_at": last.isoformat(),
        }
        now = last + timedelta(minutes=30)

        self.assertFalse(should_trigger_refresh(config, now))

    def test_enabled_and_interval_elapsed_triggers(self):
        last = datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc)
        config = {
            "enabled": True,
            "interval_minutes": 120,
            "last_triggered_at": last.isoformat(),
        }
        now = last + timedelta(minutes=121)

        self.assertTrue(should_trigger_refresh(config, now))

    def test_interval_exactly_elapsed_triggers(self):
        last = datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc)
        config = {
            "enabled": True,
            "interval_minutes": 120,
            "last_triggered_at": last.isoformat(),
        }
        now = last + timedelta(minutes=120)

        self.assertTrue(should_trigger_refresh(config, now))


if __name__ == "__main__":
    unittest.main()

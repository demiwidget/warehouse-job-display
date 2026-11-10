from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
from threading import RLock
import tempfile
import unittest

from manager_app.scan_leaderboard import ScanLeaderboardStore
from manager_app.server import create_app
from manager_app.settings_store import DEFAULT_SETTINGS, _migrate_settings
from manager_app.state import ManagerState


class FakeStore:
    def __init__(self, settings):
        self.settings = settings

    def load_settings(self):
        return self.settings


class ScanLeaderboardTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_file = Path(self.temp_dir.name) / "scan_leaderboard.sqlite3"
        self.now = datetime(2026, 11, 10, 11, 0, tzinfo=timezone.utc)
        self.store = ScanLeaderboardStore(
            data_file=self.data_file,
            now_provider=lambda: self.now,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def event(self, event_id="event-1", operator="Alice", quantity=1, workstation="PC-01"):
        return {
            "eventId": event_id,
            "eventType": "scan.completed",
            "occurredAt": "2026-11-10T10:30:00+00:00",
            "operator": operator,
            "workstation": workstation,
            "result": "success",
            "acceptedQuantity": quantity,
        }

    def test_duplicate_event_is_persisted_and_not_counted_twice(self):
        first = self.store.record(self.event())
        duplicate = self.store.record(self.event())

        self.assertFalse(first["duplicate"])
        self.assertTrue(duplicate["duplicate"])
        self.assertTrue(self.data_file.is_file())

        restarted = ScanLeaderboardStore(
            data_file=self.data_file,
            now_provider=lambda: self.now,
        )
        payload = restarted.payload(
            {"enabled": True, "visible_device_ids": ["*"], "max_rows": 12},
            device_id="screen-1",
        )
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["rows"][0]["Scans"], 1)

    def test_groups_quantities_by_operator_and_sorts_highest_first(self):
        self.store.record(self.event("event-1", "Alice", 2, "PC-01"))
        self.store.record(self.event("event-2", "Bob", 5, "PC-02"))
        self.store.record(self.event("event-3", "Alice", 3, "PC-03"))
        self.store.record(self.event("event-4", "Ignored", 0, "PC-04"))

        payload = self.store.payload(
            {"enabled": True, "visible_device_ids": ["screen-1"], "max_rows": 12},
            device_id="screen-1",
        )

        self.assertTrue(payload["visible"])
        self.assertEqual(payload["total"], 10)
        self.assertEqual([row["Operator"] for row in payload["rows"]], ["Alice", "Bob"])
        self.assertEqual(payload["rows"][0]["Workstation"], "PC-01, PC-03")

    def test_visibility_is_limited_to_selected_dashboards(self):
        config = {"enabled": True, "visible_device_ids": ["screen-1"], "max_rows": 12}
        self.assertTrue(self.store.payload(config, "screen-1")["visible"])
        self.assertFalse(self.store.payload(config, "screen-2")["visible"])

    def test_zero_quantity_and_cleared_events_still_deduplicate(self):
        zero_event = self.event("zero-event", quantity=0)
        self.assertFalse(self.store.record(zero_event)["duplicate"])
        self.assertTrue(self.store.record(zero_event)["duplicate"])

        counted_event = self.event("counted-event", quantity=4)
        self.store.record(counted_event)
        reset = self.store.reset_today()
        self.assertEqual(reset["previous_total"], 4)
        self.assertTrue(self.store.record(counted_event)["duplicate"])
        self.store.record(self.event("new-after-reset", quantity=2))
        self.assertEqual(
            self.store.payload(
                {"enabled": True, "visible_device_ids": ["*"], "max_rows": 12},
                "screen-1",
            )["total"],
            2,
        )

    def test_signed_webhook_rejects_invalid_signature(self):
        settings = deepcopy(DEFAULT_SETTINGS)
        settings["scan_leaderboard"].update(
            {"enabled": True, "signing_secret": "test-secret"}
        )
        state = ManagerState.__new__(ManagerState)
        state.lock = RLock()
        state.store = FakeStore(settings)
        state.settings = settings
        state.scan_leaderboard = self.store
        state.log_activity = lambda *_args, **_kwargs: None
        payload = self.event()
        raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = "sha256=" + hmac.new(
            b"test-secret",
            raw_body,
            hashlib.sha256,
        ).hexdigest()

        result = state.accept_zebra_scan(
            payload,
            raw_body=raw_body,
            signature=signature,
            header_event_id="event-1",
        )
        self.assertTrue(result["accepted"])
        with self.assertRaises(PermissionError):
            state.accept_zebra_scan(
                self.event("event-2"),
                raw_body=raw_body,
                signature="sha256=wrong",
                header_event_id="event-2",
            )

    def test_http_webhook_confirms_after_durable_acceptance(self):
        settings = deepcopy(DEFAULT_SETTINGS)
        settings["scan_leaderboard"].update({"enabled": True, "signing_secret": ""})
        state = ManagerState.__new__(ManagerState)
        state.lock = RLock()
        state.store = FakeStore(settings)
        state.settings = settings
        state.scan_leaderboard = self.store
        state.log_activity = lambda *_args, **_kwargs: None
        app = create_app(state)
        app.testing = True
        raw_body = json.dumps(self.event(), separators=(",", ":")).encode("utf-8")

        with app.test_client() as client:
            response = client.post(
                "/webhooks/zebra-scans",
                data=raw_body,
                headers={
                    "Content-Type": "application/json",
                    "X-Zebra-Event-Id": "event-1",
                    "X-Zebra-Event-Type": "scan.completed",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["accepted"])
        self.assertTrue(self.data_file.is_file())

    def test_settings_migration_normalizes_leaderboard_values(self):
        migrated = _migrate_settings(
            {
                "scan_leaderboard": {
                    "enabled": 1,
                    "title": "",
                    "visible_device_ids": "screen-1",
                    "signing_secret": " secret ",
                    "max_rows": 999,
                }
            }
        )
        self.assertTrue(migrated["scan_leaderboard"]["enabled"])
        self.assertEqual(migrated["scan_leaderboard"]["title"], "Scanned Leaderboard")
        self.assertEqual(migrated["scan_leaderboard"]["visible_device_ids"], ["screen-1"])
        self.assertEqual(migrated["scan_leaderboard"]["signing_secret"], "secret")
        self.assertEqual(migrated["scan_leaderboard"]["max_rows"], 50)


if __name__ == "__main__":
    unittest.main()

import unittest

from pi_maintenance import reconcile_night_sleep_config


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class PiMaintenanceTests(unittest.TestCase):
    def config(self, maintenance):
        return {
            "server": "http://manager:8765",
            "screen": "today",
            "maintenance": maintenance,
        }

    def test_clears_stale_night_sleep_when_manager_is_awake(self):
        cfg = self.config(
            {
                "enabled": True,
                "text": "Manager is sleeping\nBoards will wake in the morning",
                "clear_notifications": True,
            }
        )

        changed = reconcile_night_sleep_config(
            cfg,
            request_get=lambda *_args, **_kwargs: FakeResponse({"title": "Jobs Today", "summary": {}}),
        )

        self.assertTrue(changed)
        self.assertFalse(cfg["maintenance"]["enabled"])
        self.assertEqual(cfg["maintenance"]["mode"], "night_sleep")

    def test_keeps_night_sleep_when_manager_is_sleeping(self):
        cfg = self.config({"enabled": True, "mode": "night_sleep", "text": "Sleeping"})

        changed = reconcile_night_sleep_config(
            cfg,
            request_get=lambda *_args, **_kwargs: FakeResponse(
                {"title": "Manager Sleeping", "summary": {"Status": "Sleeping"}}
            ),
        )

        self.assertFalse(changed)
        self.assertTrue(cfg["maintenance"]["enabled"])

    def test_keeps_sleep_screen_when_manager_cannot_be_reached(self):
        cfg = self.config({"enabled": True, "mode": "night_sleep", "text": "Sleeping"})

        def unavailable(*_args, **_kwargs):
            raise OSError("offline")

        changed = reconcile_night_sleep_config(cfg, request_get=unavailable)

        self.assertFalse(changed)
        self.assertTrue(cfg["maintenance"]["enabled"])

    def test_does_not_clear_manual_maintenance_screen(self):
        cfg = self.config({"enabled": True, "mode": "manual", "text": "Work in progress"})
        requested = []

        changed = reconcile_night_sleep_config(
            cfg,
            request_get=lambda *_args, **_kwargs: requested.append(True),
        )

        self.assertFalse(changed)
        self.assertTrue(cfg["maintenance"]["enabled"])
        self.assertEqual(requested, [])

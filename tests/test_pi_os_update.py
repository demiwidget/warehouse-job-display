import json
import tempfile
import unittest
from pathlib import Path
from threading import Lock
from unittest.mock import patch

from manager_app.state import ManagerState
from pi_os_update import (
    parse_apt_simulation,
    read_os_update_status,
    reconcile_os_update_maintenance,
)


class PiOSUpdateTests(unittest.TestCase):
    def test_apt_simulation_counts_unique_updates_and_removals(self):
        output = """
Inst bash [5.2.15] (5.2.15-2 Debian:12/stable [arm64])
Inst linux-image-rpi (1.2.3 Raspberry Pi Foundation [arm64])
Inst bash [5.2.15] (5.2.15-2 Debian:12/stable [arm64])
Remv obsolete-package [1.0]
"""
        packages, removals = parse_apt_simulation(output)
        self.assertEqual(packages, ["bash", "linux-image-rpi"])
        self.assertEqual(removals, ["obsolete-package"])

    def test_status_reader_merges_file_with_runtime_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            status_path = Path(temp_dir) / "status.json"
            status_path.write_text(
                json.dumps({"state": "available", "progress": 150, "pending_count": "7"}),
                encoding="utf-8",
            )
            status = read_os_update_status(status_path)
        self.assertEqual(status["state"], "available")
        self.assertEqual(status["progress"], 100)
        self.assertEqual(status["pending_count"], 7)
        self.assertIn("os_name", status)

    def test_completed_update_screen_clears_only_after_reboot(self):
        cfg = {"maintenance": {"enabled": True, "mode": "os_update"}}
        with patch("pi_os_update.current_boot_id", return_value="same-boot"):
            changed = reconcile_os_update_maintenance(
                cfg,
                {"state": "complete", "reboot_required": True, "boot_id": "same-boot"},
            )
        self.assertFalse(changed)
        self.assertTrue(cfg["maintenance"]["enabled"])

        with patch("pi_os_update.current_boot_id", return_value="new-boot"):
            changed = reconcile_os_update_maintenance(
                cfg,
                {"state": "complete", "reboot_required": True, "boot_id": "old-boot"},
            )
        self.assertTrue(changed)
        self.assertFalse(cfg["maintenance"]["enabled"])

    def test_failed_update_releases_maintenance_screen(self):
        cfg = {"maintenance": {"enabled": True, "mode": "os_update"}}
        changed = reconcile_os_update_maintenance(cfg, {"state": "failed"})
        self.assertTrue(changed)
        self.assertFalse(cfg["maintenance"]["enabled"])

    def test_all_at_once_dispatches_screens_and_manager(self):
        state = ManagerState.__new__(ManagerState)
        state.os_update_batch_lock = Lock()
        state.os_update_batch = {"state": "idle"}
        queued = []
        manager_actions = []
        state._validate_screen_os_update_targets = lambda ids: (list(ids), {"screen-1": "Screen 1"})
        state.get_manager_status = lambda: {
            "is_manager_pi": True,
            "os_update_status": {"supported": True, "state": "current"},
        }
        state.queue_command = lambda ids, action: queued.append((list(ids), action))
        state.run_manager_command = lambda action: manager_actions.append(action)
        state.log_activity = lambda *_args, **_kwargs: None

        result = state.start_os_updates_at_once(["screen-1"], include_manager=True)

        self.assertEqual(queued, [(["screen-1"], "os_update_install")])
        self.assertEqual(manager_actions, ["os_update_install"])
        self.assertEqual(result["device_count"], 2)
        self.assertTrue(result["include_manager"])


if __name__ == "__main__":
    unittest.main()

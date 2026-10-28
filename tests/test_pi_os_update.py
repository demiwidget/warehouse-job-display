import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()

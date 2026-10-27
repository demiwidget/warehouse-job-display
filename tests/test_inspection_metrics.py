from datetime import date
import unittest

from manager_app.inspection_metrics import (
    InspectionMetrics,
    add_inspection_interval,
    build_inspection_payload,
)


class InspectionMetricTests(unittest.TestCase):
    def test_add_inspection_interval_handles_calendar_boundaries(self):
        self.assertEqual(
            add_inspection_interval(date(2026, 1, 31), 2, 1),
            date(2026, 2, 28),
        )
        self.assertEqual(
            add_inspection_interval(date(2024, 2, 29), 3, 1),
            date(2025, 2, 28),
        )

    def test_payload_counts_due_failed_and_never_tested_assets(self):
        state = {
            "results_synced_at": "2026-01-20T08:30:00",
            "inspections": {
                "1": {
                    "active": True,
                    "schedule_type": 0,
                    "schedule_interval": 10,
                }
            },
            "assets": [
                {"stock_level_id": "1", "department_id": "power", "inspection_ids": ["1"]},
                {"stock_level_id": "2", "department_id": "rigging", "inspection_ids": ["1"]},
                {"stock_level_id": "3", "department_id": "technology", "inspection_ids": ["1"]},
                {"stock_level_id": "4", "department_id": "tv", "inspection_ids": ["1"]},
                {"stock_level_id": "5", "department_id": "", "inspection_ids": ["1"]},
            ],
            "latest_results": {
                "2:1": {"inspection_at": "2026-01-10T10:00:00Z", "passed": True},
                "3:1": {"inspection_at": "2026-01-18T10:00:00Z", "passed": True},
                "4:1": {"inspection_at": "2026-01-20T10:00:00Z", "passed": False},
            },
        }
        config = {
            "due_within_days": 0,
            "show_unassigned": True,
            "department_mappings": {
                "power": "Power",
                "rigging": "Rigging",
                "technology": "Technology",
                "tv": "TV Lights",
            },
        }

        payload = build_inspection_payload(state, config, today=date(2026, 1, 20))
        counts = {row["Department"]: row["Inspections"] for row in payload["rows"]}

        self.assertEqual(payload["summary"]["Total"], 4)
        self.assertEqual(payload["summary"]["Unassigned"], 1)
        self.assertEqual(counts["Power"], 1)
        self.assertEqual(counts["Rigging"], 1)
        self.assertEqual(counts["Technology"], 0)
        self.assertEqual(counts["TV Lights"], 1)
        self.assertEqual(counts["Unassigned"], 1)

    def test_merge_latest_results_keeps_the_newest_test(self):
        latest = {
            "10:2": {
                "id": "1",
                "inspection_at": "2026-01-01T10:00:00Z",
                "passed": False,
            }
        }
        InspectionMetrics._merge_latest_results(
            latest,
            [
                {
                    "id": 2,
                    "stock_level_id": 10,
                    "inspection_id": 2,
                    "inspection_at": "2026-01-02T10:00:00Z",
                    "passed": True,
                },
                {
                    "id": 3,
                    "stock_level_id": 10,
                    "inspection_id": 2,
                    "inspection_at": "2025-12-31T10:00:00Z",
                    "passed": False,
                },
            ],
            {"10"},
            {"2"},
        )

        self.assertEqual(latest["10:2"]["id"], "2")
        self.assertTrue(latest["10:2"]["passed"])


if __name__ == "__main__":
    unittest.main()

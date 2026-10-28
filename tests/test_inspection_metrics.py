from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from manager_app.inspection_metrics import (
    InspectionMetrics,
    add_inspection_interval,
    apply_daily_inspection_changes,
    build_inspection_payload,
)


class InspectionMetricTests(unittest.TestCase):
    def test_daily_changes_compare_current_counts_with_start_of_day(self):
        baseline_payload = {
            "summary": {},
            "rows": [
                {"Tag": "power", "Department": "Power", "Inspections": 100},
                {"Tag": "rigging", "Department": "Rigging", "Inspections": 50},
            ],
        }
        _, baseline, changed = apply_daily_inspection_changes(
            baseline_payload,
            today=date(2026, 10, 28),
        )

        current_payload = {
            "summary": {},
            "rows": [
                {"Tag": "power", "Department": "Power", "Inspections": 85},
                {"Tag": "rigging", "Department": "Rigging", "Inspections": 54},
            ],
        }
        result, unchanged_baseline, baseline_changed = apply_daily_inspection_changes(
            current_payload,
            baseline,
            today=date(2026, 10, 28),
        )

        self.assertTrue(changed)
        self.assertFalse(baseline_changed)
        self.assertEqual(unchanged_baseline, baseline)
        self.assertEqual(result["rows"][0]["Daily Change"], -15)
        self.assertEqual(result["rows"][0]["Day Start"], 100)
        self.assertEqual(result["rows"][1]["Daily Change"], 4)
        self.assertEqual(result["summary"]["Daily Change"], -11)

    def test_daily_changes_reset_on_the_next_day(self):
        payload = {
            "summary": {},
            "rows": [{"Tag": "power", "Department": "Power", "Inspections": 85}],
        }
        old_baseline = {"date": "2026-10-27", "counts": {"power": 100}}

        result, baseline, changed = apply_daily_inspection_changes(
            payload,
            old_baseline,
            today=date(2026, 10, 28),
        )

        self.assertTrue(changed)
        self.assertEqual(baseline["date"], "2026-10-28")
        self.assertEqual(baseline["counts"]["power"], 85)
        self.assertEqual(result["rows"][0]["Daily Change"], 0)

    def test_daily_baseline_survives_manager_restart(self):
        with TemporaryDirectory() as temp_dir:
            cache_file = Path(temp_dir) / "inspection-cache.json"
            first_metrics = InspectionMetrics(cache_file)
            first_payload = {
                "summary": {},
                "rows": [{"Tag": "power", "Department": "Power", "Inspections": 100}],
            }
            first_metrics._apply_daily_changes(first_payload)

            restarted_metrics = InspectionMetrics(cache_file)
            current_payload = {
                "summary": {},
                "rows": [{"Tag": "power", "Department": "Power", "Inspections": 85}],
            }
            result = restarted_metrics._apply_daily_changes(current_payload)

        self.assertEqual(result["rows"][0]["Day Start"], 100)
        self.assertEqual(result["rows"][0]["Daily Change"], -15)

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

    def test_grouped_payload_subtracts_only_current_passes(self):
        state = {
            "results_synced_at": "2026-01-20T08:30:00",
            "inspections": {
                "1": {"active": True, "schedule_type": 0, "schedule_interval": 10}
            },
            "groups": [
                {
                    "department_id": "power",
                    "inspection_id": "1",
                    "product_ids": ["100"],
                    "total_assets": 4,
                }
            ],
            "latest_results": {
                "1:1": {
                    "stock_level_id": "1",
                    "product_id": "100",
                    "inspection_id": "1",
                    "inspection_at": "2026-01-18T10:00:00Z",
                    "passed": True,
                },
                "2:1": {
                    "stock_level_id": "2",
                    "product_id": "100",
                    "inspection_id": "1",
                    "inspection_at": "2026-01-20T10:00:00Z",
                    "passed": False,
                },
                "3:1": {
                    "stock_level_id": "3",
                    "product_id": "100",
                    "inspection_id": "1",
                    "inspection_at": "2026-01-05T10:00:00Z",
                    "passed": True,
                },
            },
        }
        config = {
            "due_within_days": 0,
            "show_unassigned": True,
            "department_mappings": {"power": "Power"},
        }

        payload = build_inspection_payload(state, config, today=date(2026, 1, 20))

        self.assertEqual(payload["summary"]["Total"], 3)
        self.assertEqual(payload["rows"][0]["Inspections"], 3)

    def test_grouped_result_merge_uses_embedded_product(self):
        latest = {}
        products = {"100": {"department_id": "power", "inspection_ids": ["1"]}}

        InspectionMetrics._merge_grouped_results(
            latest,
            [
                {
                    "id": 8,
                    "stock_level_id": 20,
                    "inspection_id": 1,
                    "inspection_at": "2026-01-20T10:00:00Z",
                    "passed": True,
                    "stock_level": {
                        "id": 20,
                        "item_id": 100,
                        "stock_category": 50,
                        "quantity_held": "1.0",
                        "container_stock_level_id": None,
                    },
                }
            ],
            products,
            {"1"},
        )

        self.assertEqual(latest["20:1"]["product_id"], "100")
        self.assertTrue(latest["20:1"]["passed"])

    def test_grouped_result_merge_ignores_retired_and_container_component_assets(self):
        latest = {}
        products = {"100": {"department_id": "power", "inspection_ids": ["1"]}}
        common = {
            "inspection_id": 1,
            "inspection_at": "2026-01-20T10:00:00Z",
            "passed": True,
        }

        InspectionMetrics._merge_grouped_results(
            latest,
            [
                {
                    **common,
                    "id": 1,
                    "stock_level_id": 20,
                    "stock_level": {
                        "id": 20,
                        "item_id": 100,
                        "stock_category": 50,
                        "quantity_held": "0.0",
                        "container_stock_level_id": None,
                    },
                },
                {
                    **common,
                    "id": 2,
                    "stock_level_id": 21,
                    "stock_level": {
                        "id": 21,
                        "item_id": 100,
                        "stock_category": 50,
                        "quantity_held": "1.0",
                        "container_stock_level_id": 900,
                    },
                },
            ],
            products,
            {"1"},
        )

        self.assertEqual(latest, {})

    def test_initial_failure_is_reported_instead_of_hidden_as_loading(self):
        class Client:
            api_base = "https://api.current-rms.com/api/v1"
            subdomain = "example"

        settings = {
            "current_rms": {
                "inspections": {
                    "enabled": True,
                    "department_field": "prep_department",
                    "department_mappings": {"power": "Power"},
                }
            }
        }
        with TemporaryDirectory() as temp_dir:
            metrics = InspectionMetrics(Path(temp_dir) / "inspection-cache.json")
            metrics.state = {
                "last_error": "Current RMS request failed",
                "last_attempt_at": "2999-01-01T00:00:00",
            }

            payload = metrics.payload(Client(), settings)

        self.assertIn("failed", payload["summary"]["Status"].lower())
        self.assertEqual(payload["summary"]["Error"], "Current RMS request failed")


if __name__ == "__main__":
    unittest.main()

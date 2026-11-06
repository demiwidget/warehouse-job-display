import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from webhook_tester.app import (
    EventStore,
    DOCUMENTED_EVENTS,
    event_identity,
    event_name,
    event_summary,
    normalize_custom_events,
    normalize_event_code,
)


class WebhookTesterTests(unittest.TestCase):
    def sample(self):
        return {
            "action": {
                "id": 1364,
                "subject_type": "Opportunity",
                "source_type": "OpportunityItem",
                "Action_type": "destroy_item",
                "name": "Test Job",
                "subject": {"number": "JOB-10", "name": "Test Job"},
                "source": {"name": "Cable Loom", "quantity": 2},
            }
        }

    def test_event_name_matches_current_rms_shape(self):
        self.assertEqual(event_name(self.sample()), "opportunity_destroy_item")

    def test_summary_identifies_job_and_item(self):
        summary = event_summary(self.sample())
        self.assertEqual(summary["job"], "JOB-10 · Test Job")
        self.assertEqual(summary["source"], "Cable Loom")
        self.assertEqual(summary["action_id"], "1364")

    def test_action_id_is_used_for_deduplication(self):
        payload = self.sample()
        raw = json.dumps(payload).encode()
        self.assertEqual(event_identity(payload, raw), "action:1364")

    def test_event_store_marks_second_delivery_duplicate(self):
        with TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / "events.jsonl")
            first_duplicate, _first = store.append("action:1364", self.sample())
            second_duplicate, _second = store.append("action:1364", self.sample())
        self.assertFalse(first_duplicate)
        self.assertTrue(second_duplicate)

    def test_custom_event_code_is_normalized(self):
        self.assertEqual(
            normalize_event_code(" Opportunity Book Out "), "opportunity_book_out"
        )

    def test_custom_events_ignore_invalid_and_duplicate_values(self):
        custom = normalize_custom_events(
            [
                {"event": "inspection_complete", "label": "Inspection complete"},
                {"event": "inspection_complete", "label": "Duplicate"},
                {"event": "opportunity_create", "label": "Already built in"},
                {"event": "not-valid!", "label": "Invalid"},
            ]
        )
        self.assertEqual(
            custom,
            [{"event": "inspection_complete", "label": "Inspection complete"}],
        )

    def test_official_catalogue_contains_all_documented_events_once(self):
        event_names = [event for event, _label in DOCUMENTED_EVENTS]
        self.assertEqual(len(event_names), 159)
        self.assertEqual(len(event_names), len(set(event_names)))
        self.assertIn("activity_create", event_names)
        self.assertIn("eraser_erase", event_names)
        self.assertIn("purchase_order_create", event_names)
        self.assertIn("stock_level_book_out_serialised_component", event_names)


if __name__ == "__main__":
    unittest.main()

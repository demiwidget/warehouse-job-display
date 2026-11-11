import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from webhook_tester.app import (
    ACTIVE_NOTIFICATION_EVENTS,
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

    def test_action_id_and_payload_are_used_for_deduplication(self):
        payload = self.sample()
        raw = json.dumps(payload).encode()
        identity = event_identity(payload, raw)
        self.assertTrue(identity.startswith("action:1364:payload:"))
        self.assertEqual(identity, event_identity(payload, raw))

    def test_reused_action_id_with_changed_quantity_is_not_a_duplicate(self):
        first = self.sample()
        second = json.loads(json.dumps(first))
        second["action"]["source"]["quantity"] = 3

        first_identity = event_identity(first, json.dumps(first).encode())
        second_identity = event_identity(second, json.dumps(second).encode())

        self.assertNotEqual(first_identity, second_identity)

    def test_event_store_marks_second_delivery_duplicate(self):
        with TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / "events.jsonl")
            payload = self.sample()
            identity = event_identity(payload, json.dumps(payload).encode())
            first_duplicate, _first = store.append(identity, payload)
            second_duplicate, _second = store.append(identity, payload)
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

    def test_active_notification_webhooks_are_a_small_documented_subset(self):
        documented = {event for event, _label in DOCUMENTED_EVENTS}
        self.assertEqual(len(ACTIVE_NOTIFICATION_EVENTS), 9)
        self.assertTrue(ACTIVE_NOTIFICATION_EVENTS <= documented)
        self.assertIn("opportunity_update_item", ACTIVE_NOTIFICATION_EVENTS)
        self.assertNotIn("opportunity_check_in_item", ACTIVE_NOTIFICATION_EVENTS)


if __name__ == "__main__":
    unittest.main()

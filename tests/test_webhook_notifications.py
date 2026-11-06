from datetime import datetime, timedelta
import unittest

from manager_app.current_rms import DashboardBuilder
from manager_app.settings_store import DEFAULT_SETTINGS, _migrate_settings
from manager_app.state import ManagerState


def opportunity(opportunity_id="123", days=0, returned="No"):
    starts = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=days)
    return {
        "id": opportunity_id,
        "subject": "Test Warehouse Job",
        "number": "JN-TEST-1",
        "state": 3,
        "state_name": "Order",
        "status": 0,
        "status_name": "Open",
        "customer_collecting": False,
        "customer_returning": False,
        "deliver_starts_at": starts.isoformat(),
        "deliver_ends_at": starts.isoformat(),
        "load_starts_at": starts.isoformat(),
        "owner": {"name": "Warehouse Owner"},
        "member": {"name": "Test Client"},
        "custom_fields": {"job_returned_but_unchecked": returned},
    }


class WebhookNotificationTests(unittest.TestCase):
    def setUp(self):
        self.settings = DEFAULT_SETTINGS
        self.builder = DashboardBuilder()

    def test_new_job_webhook_reuses_existing_today_popup(self):
        payload = {
            "action": {
                "id": "action-1",
                "subject_id": "123",
                "subject_type": "Opportunity",
                "action_type": "create",
                "subject": opportunity(days=0),
            }
        }

        alerts = self.builder.process_webhook(payload, self.settings)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["type"], "new_job_today")
        self.assertEqual(alerts[0]["title"], "New Job Added for Today")
        self.assertIn("Test Warehouse Job", alerts[0]["html"])
        self.assertIn("Warehouse Owner", alerts[0]["html"])

    def test_item_webhook_reuses_existing_job_change_popup_and_routing(self):
        self.builder._item_snapshots = {
            "today": {
                "123": {
                    "500": {
                        "id": 500,
                        "item_id": 88,
                        "name": "Old Lamp",
                        "quantity": "1.0",
                        "status": 5,
                        "prep_departments": ["1000010"],
                    }
                }
            }
        }
        payload = {
            "action": {
                "id": "action-2",
                "subject_id": "123",
                "subject_type": "Opportunity",
                "action_type": "update_item",
                "source_id": "500",
                "subject": opportunity(days=0),
                "source": {
                    "id": 500,
                    "item_id": 88,
                    "name": "Old Lamp",
                    "quantity": "3.0",
                    "status": 5,
                    "custom_fields": {"prep_department": "1000010"},
                },
            }
        }

        alerts = self.builder.process_webhook(payload, self.settings)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["type"], "job_changed_today")
        self.assertEqual(alerts[0]["target_departments"], ["1000010"])
        self.assertIn("Qty from 1 to 3", alerts[0]["html"])

        payload["action"]["id"] = "action-2b"
        payload["action"]["source"]["quantity"] = "4.0"
        next_alerts = self.builder.process_webhook(payload, self.settings)
        self.assertIn("Qty from 3 to 4", next_alerts[0]["html"])

    def test_returned_webhook_uses_existing_returned_popup(self):
        payload = {
            "action": {
                "id": "action-3",
                "subject_id": "123",
                "subject_type": "Opportunity",
                "action_type": "update",
                "subject": opportunity(days=0, returned="Yes"),
            }
        }

        alerts = self.builder.process_webhook(payload, self.settings)

        returned = [alert for alert in alerts if alert["type"] == "job_returned"]
        self.assertEqual(len(returned), 1)
        self.assertIn("A job has been returned", returned[0]["html"])

    def test_polling_is_excluded_only_while_webhook_pilot_is_enabled(self):
        state = ManagerState.__new__(ManagerState)
        settings = {"alerts": {"webhooks": {"enabled": False, "target_device_ids": ["test-pi"]}}}
        self.assertEqual(state._webhook_target_ids(settings), set())
        settings["alerts"]["webhooks"]["enabled"] = True
        self.assertEqual(state._webhook_target_ids(settings), {"test-pi"})

    def test_settings_limit_webhook_pilot_to_one_screen(self):
        migrated = _migrate_settings(
            {"alerts": {"webhooks": {"enabled": True, "target_device_ids": ["one", "two"]}}}
        )
        self.assertEqual(migrated["alerts"]["webhooks"]["target_device_ids"], ["one"])


if __name__ == "__main__":
    unittest.main()

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from manager_app.api_metrics import CurrentRMSApiCounter
from manager_app.current_rms import CurrentRMSClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class CurrentRMSRequestControlTests(unittest.TestCase):
    def settings(self):
        return {
            "current_rms": {
                "api_key": "test-key",
                "subdomain": "test-subdomain",
                "opportunity_includes": ["owner", "member"],
            }
        }

    def test_api_counter_reports_rolling_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            counter = CurrentRMSApiCounter(
                Path(directory) / "calls.json",
                rate_limit=7,
                rate_window_seconds=60,
            )
            counter.record()
            counter.record()

            snapshot = counter.snapshot()

        self.assertEqual(snapshot["today"], 2)
        self.assertEqual(snapshot["last_minute"], 2)
        self.assertEqual(snapshot["rate_limit"], 7)
        self.assertEqual(snapshot["rate_window_seconds"], 60)

    def test_opportunity_list_requests_configured_associations(self):
        client = CurrentRMSClient(self.settings())
        client.get = Mock(
            return_value=FakeResponse(
                {
                    "opportunities": [],
                    "meta": {"total_row_count": 0},
                }
            )
        )

        client.fetch_view("123")

        params = client.get.call_args.kwargs["params"]
        self.assertIn(("include[]", "owner"), params)
        self.assertIn(("include[]", "member"), params)

    def test_complete_list_record_does_not_trigger_a_detail_request(self):
        client = CurrentRMSClient(self.settings())
        opportunity = {
            "id": 42,
            "custom_fields": {},
            "customer_collecting": False,
            "customer_returning": False,
            "deliver_starts_at": "2026-11-10T09:00:00Z",
            "deliver_ends_at": "2026-11-10T10:00:00Z",
            "owner": {"name": "Owner"},
            "member": {"name": "Customer"},
        }
        client.get = Mock(
            return_value=FakeResponse(
                {
                    "opportunities": [opportunity],
                    "meta": {"total_row_count": 1},
                }
            )
        )
        client.fetch_opportunity = Mock()

        result = client.fetch_view("123")

        self.assertEqual(result["opportunities"], [opportunity])
        client.fetch_opportunity.assert_not_called()

    def test_duplicate_detail_requests_share_one_inflight_call(self):
        client = CurrentRMSClient(self.settings())
        request_started = threading.Event()
        release_request = threading.Event()

        def fetch_opportunity(_opportunity_id):
            request_started.set()
            release_request.wait(timeout=2)
            return {"id": 42, "subject": "Shared result"}

        client.fetch_opportunity = Mock(side_effect=fetch_opportunity)
        results = []

        def fetch_detail():
            results.append(client._cached_opportunity_detail(42))

        first = threading.Thread(target=fetch_detail)
        second = threading.Thread(target=fetch_detail)
        first.start()
        self.assertTrue(request_started.wait(timeout=1))
        second.start()
        time.sleep(0.05)
        release_request.set()
        first.join(timeout=2)
        second.join(timeout=2)

        self.assertEqual(client.fetch_opportunity.call_count, 1)
        self.assertEqual(results, [{"id": 42, "subject": "Shared result"}] * 2)


if __name__ == "__main__":
    unittest.main()

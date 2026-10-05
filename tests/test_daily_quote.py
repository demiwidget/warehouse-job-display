import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from threading import RLock

from manager_app.daily_quote import DailyQuoteService
from manager_app.state import ManagerState


class FakeResponse:
    def __init__(self, payload, ok=True, status_code=200):
        self.payload = payload
        self.ok = ok
        self.status_code = status_code

    def json(self):
        return self.payload


class DailyQuoteServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_file = Path(self.temp_dir.name) / "daily_quote.json"
        self.now = datetime(2026, 10, 5, 6, 15, 0)
        self.calls = []

    def tearDown(self):
        self.temp_dir.cleanup()

    def settings(self):
        return {
            "daily_quote": {
                "enabled": True,
                "api_key": "test-key",
                "model": "gpt-6-luna",
                "company_name": "Limelite Lighting",
                "management_names": "Dave, Ed and Matt",
                "prompt": "Cheeky but kind management banter.",
                "signature": "— created by AI",
            }
        }

    def successful_post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(
            {
                "output": [
                    {"type": "reasoning", "summary": []},
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Management: turning tea into decisions since sunrise.",
                            }
                        ],
                    },
                ]
            }
        )

    def test_generates_once_per_day_and_persists_the_quote(self):
        service = DailyQuoteService(
            cache_file=self.cache_file,
            request_post=self.successful_post,
            now_provider=lambda: self.now,
        )

        first = service.ensure_current(self.settings())
        second = service.ensure_current(self.settings())

        self.assertTrue(first["generated"])
        self.assertNotIn("generated", second)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(first["visible"])
        self.assertEqual(first["generated_for"], "2026-10-05")
        self.assertTrue(first["quote"].endswith("— created by AI"))
        self.assertEqual(self.calls[0][0], "https://api.openai.com/v1/responses")
        self.assertFalse(self.calls[0][1]["json"]["store"])
        self.assertEqual(self.calls[0][1]["json"]["reasoning"], {"effort": "none"})

        restarted = DailyQuoteService(cache_file=self.cache_file, now_provider=lambda: self.now)
        self.assertEqual(restarted.status(self.settings())["quote"], first["quote"])

    def test_failed_refresh_keeps_the_previous_quote(self):
        service = DailyQuoteService(
            cache_file=self.cache_file,
            request_post=self.successful_post,
            now_provider=lambda: self.now,
        )
        original = service.ensure_current(self.settings())["quote"]

        def failed_post(_url, **_kwargs):
            return FakeResponse(
                {"error": {"message": "Temporary API problem"}},
                ok=False,
                status_code=503,
            )

        service.request_post = failed_post
        failed = service.ensure_current(self.settings(), force=True)

        self.assertFalse(failed["generated"])
        self.assertEqual(failed["quote"], original)
        self.assertEqual(failed["error"], "Temporary API problem")

    def test_missing_api_key_does_not_make_a_request(self):
        service = DailyQuoteService(
            cache_file=self.cache_file,
            request_post=self.successful_post,
            now_provider=lambda: self.now,
        )
        settings = self.settings()
        settings["daily_quote"]["api_key"] = ""

        result = service.ensure_current(settings)

        self.assertFalse(result["configured"])
        self.assertFalse(result["visible"])
        self.assertEqual(self.calls, [])
        self.assertIn("API key", result["error"])

    def test_dashboard_bundle_contains_only_public_quote_fields(self):
        settings = self.settings()

        class FakeStore:
            def load_settings(self):
                return settings

        class FakeDashboard:
            def build(self, screen, _settings):
                return {"title": screen.title(), "rows": []}

        class FakeQuote:
            def status(self, _settings):
                return {
                    "visible": True,
                    "quote": "Keep calm and blame the flight case. — created by AI",
                    "generated_for": "2026-10-05",
                    "stale": False,
                    "configured": True,
                    "model": "gpt-6-luna",
                    "error": "private diagnostic",
                }

        state = ManagerState.__new__(ManagerState)
        state.lock = RLock()
        state.dashboard_lock = RLock()
        state.store = FakeStore()
        state.settings = settings
        state.dashboard = FakeDashboard()
        state.daily_quote = FakeQuote()
        state.sync_night_sleep = lambda _settings: False

        payload = state.all_screen_payloads()["daily_quote"]

        self.assertEqual(
            set(payload),
            {"visible", "quote", "generated_for", "stale"},
        )
        self.assertNotIn("configured", payload)
        self.assertNotIn("error", payload)


if __name__ == "__main__":
    unittest.main()

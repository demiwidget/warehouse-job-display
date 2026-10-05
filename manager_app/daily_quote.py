import json
import os
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from time import monotonic

import requests

from manager_app.settings_store import DATA_DIR


DAILY_QUOTE_FILE = DATA_DIR / "daily_quote.json"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
AUTOMATIC_RETRY_SECONDS = 15 * 60


def _atomic_write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temp_name).replace(path)
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except Exception:
                pass


class DailyQuoteService:
    def __init__(self, cache_file=DAILY_QUOTE_FILE, request_post=None, now_provider=None):
        self.cache_file = Path(cache_file)
        self.request_post = request_post or requests.post
        self.now_provider = now_provider or datetime.now
        self.state_lock = Lock()
        self.generation_lock = Lock()
        self.generating = False
        self.retry_after = 0.0
        self.cache = self._load_cache()

    def _load_cache(self):
        try:
            payload = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        history = payload.get("history", [])
        if not isinstance(history, list):
            history = []
        return {
            "date": str(payload.get("date") or ""),
            "quote": str(payload.get("quote") or "").strip(),
            "generated_at": str(payload.get("generated_at") or ""),
            "model": str(payload.get("model") or ""),
            "history": [str(item).strip() for item in history if str(item).strip()][-12:],
            "last_error": str(payload.get("last_error") or "").strip(),
        }

    def _save_cache(self):
        with self.state_lock:
            payload = deepcopy(self.cache)
        _atomic_write_json(self.cache_file, payload)

    def _settings(self, settings):
        config = settings.get("daily_quote", {}) if isinstance(settings, dict) else {}
        return config if isinstance(config, dict) else {}

    def status(self, settings):
        config = self._settings(settings)
        today = self.now_provider().date().isoformat()
        enabled = bool(config.get("enabled", True))
        configured = bool(str(config.get("api_key") or "").strip())
        with self.state_lock:
            cache = deepcopy(self.cache)
            generating = self.generating
        quote_text = str(cache.get("quote") or "").strip()
        error = str(cache.get("last_error") or "").strip()
        if enabled and not configured and not error:
            error = "Add an OpenAI API key in the PC Manager to generate the daily quote."
        return {
            "enabled": enabled,
            "configured": configured,
            "visible": bool(enabled and quote_text),
            "quote": quote_text,
            "generated_for": str(cache.get("date") or ""),
            "generated_at": str(cache.get("generated_at") or ""),
            "model": str(cache.get("model") or config.get("model") or "gpt-6-luna"),
            "stale": bool(quote_text and cache.get("date") != today),
            "generating": generating,
            "error": error,
        }

    def ensure_current(self, settings, force=False):
        config = self._settings(settings)
        if not bool(config.get("enabled", True)):
            return self.status(settings)

        api_key = str(config.get("api_key") or "").strip()
        if not api_key:
            return self.status(settings)

        today = self.now_provider().date().isoformat()
        with self.state_lock:
            current_date = str(self.cache.get("date") or "")
        if not force and current_date == today:
            return self.status(settings)
        if not force and monotonic() < self.retry_after:
            return self.status(settings)

        if not self.generation_lock.acquire(blocking=False):
            result = self.status(settings)
            result["error"] = "A daily quote is already being generated."
            return result

        with self.state_lock:
            self.generating = True
        attempted = False
        generated = False
        try:
            attempted = True
            quote_text = self._request_quote(config, today)
            now = self.now_provider()
            with self.state_lock:
                previous_quote = str(self.cache.get("quote") or "").strip()
                history = list(self.cache.get("history") or [])
                if previous_quote and previous_quote != quote_text:
                    history.append(previous_quote)
                self.cache = {
                    "date": today,
                    "quote": quote_text,
                    "generated_at": now.isoformat(timespec="seconds"),
                    "model": str(config.get("model") or "gpt-6-luna").strip(),
                    "history": history[-12:],
                    "last_error": "",
                }
            self.retry_after = 0.0
            self._save_cache()
            generated = True
        except Exception as error:
            with self.state_lock:
                self.cache["last_error"] = str(error)
            self.retry_after = monotonic() + AUTOMATIC_RETRY_SECONDS
            self._save_cache()
        finally:
            with self.state_lock:
                self.generating = False
            self.generation_lock.release()

        result = self.status(settings)
        result["attempted"] = attempted
        result["generated"] = generated
        return result

    def _request_quote(self, config, today):
        model = str(config.get("model") or "gpt-6-luna").strip() or "gpt-6-luna"
        company_name = str(config.get("company_name") or "Limelite Lighting").strip()
        management_names = str(config.get("management_names") or "management").strip()
        prompt_guidance = str(config.get("prompt") or "").strip()
        signature = str(config.get("signature") or "— created by AI").strip()

        with self.state_lock:
            recent_quotes = list(self.cache.get("history") or [])
            current_quote = str(self.cache.get("quote") or "").strip()
        if current_quote:
            recent_quotes.append(current_quote)
        recent_text = "\n".join(f"- {quote}" for quote in recent_quotes[-6:]) or "- None yet"

        instructions = (
            "Write one original, short daily quote or joke for a workplace dashboard. "
            "It must be safe for work, good-natured and affectionate: no profanity, sexual content, "
            "protected-characteristic jokes, bullying, cruelty or personal attacks. Keep it under 35 words. "
            "Return only the quote text without markdown, labels or surrounding quotation marks."
        )
        input_text = (
            f"Date: {today}\n"
            f"Company: {company_name}\n"
            f"Management names or description: {management_names}\n"
            f"Creative direction: {prompt_guidance}\n"
            "Avoid repeating these recent quotes:\n"
            f"{recent_text}\n"
            f"End with this exact signature: {signature}"
        )
        request_payload = {
            "model": model,
            "instructions": instructions,
            "input": input_text,
            "max_output_tokens": 250,
            "store": False,
        }
        if "luna" in model.casefold():
            request_payload["reasoning"] = {"effort": "none"}

        response = self.request_post(
            OPENAI_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {str(config.get('api_key') or '').strip()}",
                "Content-Type": "application/json",
            },
            json=request_payload,
            timeout=40,
        )
        try:
            payload = response.json()
        except Exception:
            payload = {}
        if not response.ok:
            error_payload = payload.get("error", {}) if isinstance(payload, dict) else {}
            message = str(error_payload.get("message") or f"OpenAI returned HTTP {response.status_code}.")
            raise RuntimeError(message)

        quote_text = self._extract_output_text(payload)
        return self._clean_quote(quote_text, signature)

    @staticmethod
    def _extract_output_text(payload):
        if not isinstance(payload, dict):
            raise RuntimeError("OpenAI returned an invalid response.")
        direct_text = str(payload.get("output_text") or "").strip()
        if direct_text:
            return direct_text

        parts = []
        for output_item in payload.get("output", []) or []:
            if not isinstance(output_item, dict) or output_item.get("type") != "message":
                continue
            for content_item in output_item.get("content", []) or []:
                if not isinstance(content_item, dict) or content_item.get("type") != "output_text":
                    continue
                text = str(content_item.get("text") or "").strip()
                if text:
                    parts.append(text)
        if not parts:
            raise RuntimeError("OpenAI did not return quote text.")
        return " ".join(parts)

    @staticmethod
    def _clean_quote(value, signature):
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        text = re.sub(r"^(daily\s+)?(quote|joke)\s*:\s*", "", text, flags=re.IGNORECASE)
        text = text.strip(" \t\r\n\"'“”")
        if not text:
            raise RuntimeError("OpenAI returned an empty quote.")

        signature = str(signature or "").strip()
        if signature and signature.casefold() not in text.casefold():
            text = f"{text} {signature}"
        if len(text) > 420:
            raise RuntimeError("OpenAI returned a quote that was too long.")
        return text

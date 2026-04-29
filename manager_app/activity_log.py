import json
from datetime import datetime
from pathlib import Path
from threading import RLock

from manager_app.settings_store import DATA_DIR


ACTIVITY_FILE = DATA_DIR / "activity.log"
MAX_STORED_LINES = 2500
SECRET_KEYS = ("api_key", "auth", "token", "password", "secret")


def _safe_text(value):
    return str(value or "").replace("\r", " ").replace("\n", " ").strip()


def _redact(value):
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            key_text = str(key)
            if any(secret in key_text.lower() for secret in SECRET_KEYS):
                cleaned[key_text] = "***"
            else:
                cleaned[key_text] = _redact(item)
        return cleaned
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


class ActivityLog:
    def __init__(self, path=ACTIVITY_FILE):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()

    def append(self, category, message, level="info", details=None):
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "level": _safe_text(level).lower() or "info",
            "category": _safe_text(category) or "Manager",
            "message": _safe_text(message),
            "details": _redact(details or {}),
        }

        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
            self._trim_if_needed()
        return entry

    def list_entries(self, category="All", level="All", limit=500):
        category = _safe_text(category)
        level = _safe_text(level).lower()
        try:
            max_rows = max(1, min(2000, int(limit)))
        except Exception:
            max_rows = 500

        with self.lock:
            rows = self._read_entries()

        filtered = []
        for entry in reversed(rows):
            if category and category.lower() != "all" and str(entry.get("category", "")).lower() != category.lower():
                continue
            if level and level != "all" and str(entry.get("level", "")).lower() != level:
                continue
            filtered.append(entry)
            if len(filtered) >= max_rows:
                break
        return filtered

    def clear(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")

    def _read_entries(self):
        if not self.path.exists():
            return []

        entries = []
        for line in self.path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                entries.append(item)
        return entries

    def _trim_if_needed(self):
        if not self.path.exists():
            return
        lines = self.path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if len(lines) <= MAX_STORED_LINES:
            return
        self.path.write_text("\n".join(lines[-MAX_STORED_LINES:]) + "\n", encoding="utf-8")

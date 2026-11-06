from collections import deque
from datetime import date, datetime
import json
import os
from pathlib import Path
from threading import Lock
from time import monotonic, time

from manager_app.settings_store import PROJECT_ROOT


COUNTER_PATH = PROJECT_ROOT / "manager_data" / "current_rms_api_calls.json"


class CurrentRMSApiCounter:
    """Small, process-wide counter for requests sent to Current RMS."""

    def __init__(self, path=COUNTER_PATH):
        self.path = Path(path)
        self.lock = Lock()
        self.day = date.today().isoformat()
        self.today = 0
        self.session = 0
        self.recent = deque()
        self.updated_at = ""
        self._dirty = False
        self._last_save = 0.0
        self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            data = {}
        if str(data.get("date") or "") == self.day:
            try:
                self.today = max(0, int(data.get("today", 0)))
            except (TypeError, ValueError):
                self.today = 0

    def _roll_day(self):
        current_day = date.today().isoformat()
        if current_day != self.day:
            self.day = current_day
            self.today = 0
            self.recent.clear()
            self._dirty = True

    def record(self):
        now = time()
        with self.lock:
            self._roll_day()
            self.today += 1
            self.session += 1
            self.recent.append(now)
            self.updated_at = datetime.now().isoformat(timespec="seconds")
            self._dirty = True
            self._trim_recent(now)
            self._save_if_due()

    def _trim_recent(self, now):
        cutoff = now - 60
        while self.recent and self.recent[0] < cutoff:
            self.recent.popleft()

    def snapshot(self):
        now = time()
        with self.lock:
            self._roll_day()
            self._trim_recent(now)
            self._save_if_due(force=True)
            return {
                "date": self.day,
                "today": self.today,
                "session": self.session,
                "last_minute": len(self.recent),
                "updated_at": self.updated_at,
            }

    def _save_if_due(self, force=False):
        if not self._dirty:
            return
        now = monotonic()
        if not force and now - self._last_save < 30:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(
                    {
                        "date": self.day,
                        "today": self.today,
                        "updated_at": self.updated_at,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        except OSError:
            return
        self._dirty = False
        self._last_save = now


CURRENT_RMS_API_COUNTER = CurrentRMSApiCounter()

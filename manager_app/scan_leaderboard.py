import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import RLock

from manager_app.settings_store import DATA_DIR


SCAN_LEADERBOARD_FILE = DATA_DIR / "scan_leaderboard.sqlite3"
RETENTION_DAYS = 31


def _parse_timestamp(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


class ScanLeaderboardStore:
    def __init__(self, data_file=SCAN_LEADERBOARD_FILE, now_provider=None):
        self.data_file = Path(data_file)
        self.now_provider = now_provider or (lambda: datetime.now().astimezone())
        self.lock = RLock()
        self._initialize()

    def _connect(self):
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.data_file, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self):
        with self.lock, self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scan_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    occurred_day TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    operator TEXT NOT NULL,
                    workstation TEXT NOT NULL,
                    accepted_quantity INTEGER NOT NULL,
                    received_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS scan_events_day_idx ON scan_events (occurred_day, received_at)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scan_resets (
                    day TEXT PRIMARY KEY,
                    reset_after_rowid INTEGER NOT NULL
                )
                """
            )
            connection.commit()

    def _local_day(self, occurred_at):
        parsed = _parse_timestamp(occurred_at)
        if parsed is None:
            return self.now_provider().date().isoformat()
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone()
        return parsed.date().isoformat()

    def _prune(self, connection):
        cutoff = (self.now_provider().date() - timedelta(days=RETENTION_DAYS - 1)).isoformat()
        connection.execute("DELETE FROM scan_events WHERE occurred_day < ?", (cutoff,))
        connection.execute("DELETE FROM scan_resets WHERE day < ?", (cutoff,))

    def record(self, payload):
        event_id = str(payload.get("eventId") or "").strip()
        occurred_at = str(payload.get("occurredAt") or "").strip()
        event_type = str(payload.get("eventType") or "").strip()
        operator = str(payload.get("operator") or "Unknown operator").strip() or "Unknown operator"
        workstation = str(payload.get("workstation") or "").strip()
        accepted_quantity = max(0, int(payload.get("acceptedQuantity", 0) or 0))
        day_key = self._local_day(occurred_at)
        now_text = self.now_provider().isoformat(timespec="microseconds")
        counted_quantity = accepted_quantity if event_type == "scan.completed" else 0

        with self.lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO scan_events (
                    event_id, event_type, occurred_day, occurred_at, operator,
                    workstation, accepted_quantity, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event_type,
                    day_key,
                    occurred_at or now_text,
                    operator,
                    workstation,
                    counted_quantity,
                    now_text,
                ),
            )
            if cursor.rowcount == 0:
                existing = connection.execute(
                    "SELECT occurred_day FROM scan_events WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                connection.commit()
                return {
                    "accepted": True,
                    "duplicate": True,
                    "event_id": event_id,
                    "day": str(existing["occurred_day"] if existing else day_key),
                }

            self._prune(connection)
            connection.commit()

        return {
            "accepted": True,
            "duplicate": False,
            "event_id": event_id,
            "day": day_key,
            "counted_quantity": counted_quantity,
        }

    def _day_rows(self, connection, day_key):
        reset = connection.execute(
            "SELECT reset_after_rowid FROM scan_resets WHERE day = ?",
            (day_key,),
        ).fetchone()
        reset_after_rowid = int(reset["reset_after_rowid"] if reset else 0)
        return connection.execute(
            """
            SELECT rowid, event_id, operator, workstation, accepted_quantity, occurred_at, received_at
            FROM scan_events
            WHERE occurred_day = ?
              AND event_type = 'scan.completed'
              AND accepted_quantity > 0
              AND rowid > ?
            ORDER BY rowid ASC
            """,
            (day_key, reset_after_rowid),
        ).fetchall()

    def payload(self, config, device_id=""):
        config = config if isinstance(config, dict) else {}
        enabled = bool(config.get("enabled", False))
        visible_ids = {
            str(value).strip()
            for value in (config.get("visible_device_ids") or [])
            if str(value).strip()
        }
        device_id = str(device_id or "").strip()
        visible = enabled and ("*" in visible_ids or device_id in visible_ids)
        today = self.now_provider().date()
        day_key = today.isoformat()
        max_rows = max(3, min(50, int(config.get("max_rows", 12) or 12)))

        with self.lock, self._connection() as connection:
            events = self._day_rows(connection, day_key)

        operators = {}
        total = 0
        last_scan_at = ""
        for event in events:
            operator = str(event["operator"] or "Unknown operator")
            quantity = int(event["accepted_quantity"] or 0)
            total += quantity
            operator_data = operators.setdefault(
                operator,
                {"count": 0, "workstations": [], "last_scan_at": ""},
            )
            operator_data["count"] += quantity
            workstation = str(event["workstation"] or "").strip()
            if workstation and workstation not in operator_data["workstations"]:
                operator_data["workstations"].append(workstation)
            operator_data["last_scan_at"] = str(event["occurred_at"] or "")
            last_scan_at = str(event["occurred_at"] or "")

        rows = []
        for operator, operator_data in operators.items():
            parsed = _parse_timestamp(operator_data["last_scan_at"])
            if parsed and parsed.tzinfo is not None:
                parsed = parsed.astimezone()
            rows.append(
                {
                    "Operator": operator,
                    "Scans": operator_data["count"],
                    "Workstation": ", ".join(operator_data["workstations"][-8:]),
                    "Last Scan": parsed.strftime("%H:%M") if parsed else "",
                }
            )
        rows.sort(key=lambda row: (-row["Scans"], row["Operator"].casefold()))
        for rank, row in enumerate(rows, start=1):
            row["Rank"] = rank

        return {
            "enabled": enabled,
            "visible": visible,
            "title": str(config.get("title") or "Scanned Leaderboard"),
            "date": day_key,
            "date_label": today.strftime("Today, %d %b %Y"),
            "total": total,
            "operator_count": len(rows),
            "last_scan_at": last_scan_at,
            "rows": rows[:max_rows],
            "max_rows": max_rows,
        }

    def reset_today(self):
        today_key = self.now_provider().date().isoformat()
        with self.lock, self._connection() as connection:
            events = self._day_rows(connection, today_key)
            previous_total = sum(int(event["accepted_quantity"] or 0) for event in events)
            latest_event = connection.execute(
                "SELECT COALESCE(MAX(rowid), 0) AS rowid FROM scan_events WHERE occurred_day = ?",
                (today_key,),
            ).fetchone()
            reset_after_rowid = int(latest_event["rowid"] if latest_event else 0)
            connection.execute(
                """
                INSERT INTO scan_resets (day, reset_after_rowid) VALUES (?, ?)
                ON CONFLICT(day) DO UPDATE SET reset_after_rowid = excluded.reset_after_rowid
                """,
                (today_key, reset_after_rowid),
            )
            connection.commit()
        return {
            "day": today_key,
            "cleared": previous_total > 0,
            "previous_total": previous_total,
        }

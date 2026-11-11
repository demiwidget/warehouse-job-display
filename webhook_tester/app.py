from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sys
from threading import Lock, Thread
import time
from typing import Any, Callable

from flask import Flask, jsonify, request
from PySide6.QtCore import QObject, QProcess, QTimer, Qt, Signal
from PySide6.QtGui import QCloseEvent, QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
import requests
from werkzeug.serving import make_server


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "webhook_test_data"
SETTINGS_PATH = PROJECT_ROOT / "manager_data" / "settings.json"
CONFIG_PATH = DATA_DIR / "config.json"
EVENTS_PATH = DATA_DIR / "events.jsonl"
CLOUDFLARED_PATH = DATA_DIR / "cloudflared.exe"
CLOUDFLARED_DOWNLOAD_URL = (
    "https://github.com/cloudflare/cloudflared/releases/latest/download/"
    "cloudflared-windows-amd64.exe"
)
WEBHOOK_NAME_PREFIX = "Warehouse Webhook Tester"
LOCAL_PORT = 8787

DEFAULT_EVENTS = (
    ("opportunity_create", "Job added"),
    ("opportunity_update", "Job updated"),
    ("opportunity_destroy", "Job deleted"),
    ("opportunity_cancel", "Job cancelled"),
    ("opportunity_mark_as_dead", "Job marked dead"),
    ("opportunity_create_item", "Item added"),
    ("opportunity_update_item", "Item updated"),
    ("opportunity_destroy_item", "Item removed"),
)

# These are the only Current RMS events translated into live warehouse
# notifications by manager_app.current_rms.DashboardBuilder.
ACTIVE_NOTIFICATION_EVENTS = frozenset(
    {
        "opportunity_create",
        "opportunity_update",
        "opportunity_destroy",
        "opportunity_confirm",
        "opportunity_convert_to_order",
        "opportunity_reinstate",
        "opportunity_create_item",
        "opportunity_update_item",
        "opportunity_destroy_item",
    }
)

GENERIC_ACTIONS = (
    "create",
    "update",
    "destroy",
    "discuss",
    "attach",
    "detach",
    "custom_view_export",
)

# Official catalogue: https://help.current-rms.com/en/collections/2943050-webhooks
WEBHOOK_ACTION_GROUPS = (
    ("Activity", "activity", GENERIC_ACTIONS + ("complete", "reinstate")),
    (
        "Discussion",
        "discussion",
        ("comment", "create_participant", "mute_participant", "unmute_participant", "open_email"),
    ),
    ("Document layout", "document_layout", ("create", "destroy", "update", "attach", "detach")),
    ("Erase", "eraser", ("erase",)),
    (
        "Export",
        "export",
        ("export_complete", "qb_export_complete", "xero_export_complete", "sage_export_complete", "woocommerce_export_complete"),
    ),
    ("Import", "import", ("import_complete", "qb_import_complete", "xero_import_complete", "sage_import_complete")),
    (
        "Invoice",
        "invoice",
        GENERIC_ACTIONS
        + (
            "create_item", "destroy_item", "issue", "mark_as_paid", "mark_as_unpaid",
            "post", "print", "void", "unvoid", "update_item", "create_transaction",
            "update_transaction", "destroy_transaction",
        ),
    ),
    ("Item", "item", GENERIC_ACTIONS + ("import_create", "import_update")),
    (
        "Member",
        "member",
        GENERIC_ACTIONS + ("lawful_basis_type_changed", "import_create", "import_update", "merge"),
    ),
    (
        "Opportunity",
        "opportunity",
        GENERIC_ACTIONS
        + (
            "allocate", "allocate_item", "auto_allocate", "auto_return", "book_out",
            "book_out_item", "cancel", "check_in", "check_in_item", "checkout",
            "clear_deal_price", "complete", "confirm", "convert_to_draft",
            "convert_to_order", "convert_to_quotation", "create_item", "destroy_item",
            "enable_auto_costing", "finalise", "mark_as_provisional", "mark_as_reserved",
            "mark_as_lost", "mark_as_dead", "prepare", "prepare_item", "print",
            "reinstate", "revert_status", "revert_to_quotation", "set_deal_price",
            "toggle_pricing_locked", "update_item", "swap_component",
        ),
    ),
    (
        "Purchase order",
        "purchase_order",
        GENERIC_ACTIONS
        + (
            "create_back_to_back", "authorise", "complete", "convert_to_order",
            "create_item", "destroy_item", "mark_as_sent", "print", "reopen",
            "set_expected", "unauthorise", "update_item",
        ),
    ),
    ("Project", "project", GENERIC_ACTIONS + ("close", "reopen")),
    ("Quarantine", "quarantine", GENERIC_ACTIONS + ("book_out",)),
    ("Rate definition", "rate_definition", ("create", "destroy", "update")),
    (
        "Stock level",
        "stock_level",
        (
            "update", "destroy", "attach", "detach", "create_serialised_component",
            "destroy_serialised_component", "swap_serialised_component",
            "book_out_serialised_component", "import_create", "import_update",
        ),
    ),
)

DEFAULT_EVENT_LABELS = dict(DEFAULT_EVENTS)
DOCUMENTED_EVENTS = tuple(
    (
        f"{subject}_{action}",
        f"{category} — {DEFAULT_EVENT_LABELS.get(f'{subject}_{action}', action.replace('_', ' ').title())}",
    )
    for category, subject, actions in WEBHOOK_ACTION_GROUPS
    for action in actions
)

WAREHOUSE_EVENT_PRESETS = (
    ("Choose a warehouse example…", "", ""),
    ("Job prepared", "Job prepared", "opportunity_prepare"),
    ("Job booked out", "Job booked out", "opportunity_book_out"),
    ("Job checked in", "Job checked in", "opportunity_check_in"),
    ("Job completed / returned", "Job completed / returned", "opportunity_complete"),
    ("Order confirmed", "Order confirmed", "opportunity_confirm"),
    ("Item allocated / scanned", "Item allocated / scanned", "opportunity_allocate_item"),
    ("Item prepared / scanned", "Item prepared / scanned", "opportunity_prepare_item"),
    ("Item booked out / scanned", "Item booked out / scanned", "opportunity_book_out_item"),
    ("Item checked in / scanned", "Item checked in / scanned", "opportunity_check_in_item"),
)

CUSTOM_EVENT_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")


def normalize_event_code(value: Any) -> str:
    return re.sub(r"_+", "_", str(value or "").strip().lower().replace(" ", "_"))


def normalize_custom_events(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    results: list[dict[str, str]] = []
    seen = {event for event, _label in DOCUMENTED_EVENTS}
    for item in value:
        if not isinstance(item, dict):
            continue
        event = normalize_event_code(item.get("event"))
        label = str(item.get("label") or "").strip()
        if not CUSTOM_EVENT_PATTERN.fullmatch(event) or event in seen:
            continue
        results.append({"event": event, "label": label or event.replace("_", " ").title()})
        seen.add(event)
    return results


def load_json(path: Path, default: Any) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default
    return value


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def load_or_create_config() -> dict[str, Any]:
    config = load_json(CONFIG_PATH, {})
    if not isinstance(config, dict):
        config = {}
    if not str(config.get("callback_secret", "")).strip():
        config["callback_secret"] = secrets.token_urlsafe(32)
        save_json(CONFIG_PATH, config)
    return config


def load_current_rms_credentials(path: Path = SETTINGS_PATH) -> dict[str, str]:
    settings = load_json(path, {})
    rms = settings.get("current_rms", {}) if isinstance(settings, dict) else {}
    credentials = {
        "api_base": str(rms.get("api_base", "")).strip().rstrip("/"),
        "subdomain": str(rms.get("subdomain", "")).strip(),
        "api_key": str(rms.get("api_key", "")).strip(),
    }
    missing = [name for name, value in credentials.items() if not value]
    if missing:
        raise RuntimeError(f"Current RMS settings are missing: {', '.join(missing)}")
    return credentials


def masked_key(value: str) -> str:
    if not value:
        return "Not configured"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:3]}{'*' * min(12, len(value) - 6)}{value[-3:]}"


def event_identity(payload: dict[str, Any], raw_body: bytes) -> str:
    try:
        canonical_body = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    except (TypeError, ValueError):
        canonical_body = raw_body
    payload_hash = hashlib.sha256(canonical_body).hexdigest()
    action = payload.get("action", {}) if isinstance(payload, dict) else {}
    action_id = action.get("id") if isinstance(action, dict) else None
    if action_id not in (None, ""):
        # Current RMS can reuse an action ID when the same item is changed
        # again. Pair it with the payload so exact retries are ignored while
        # later, materially different changes are still forwarded.
        return f"action:{action_id}:payload:{payload_hash}"
    return "body:" + payload_hash


def event_name(payload: dict[str, Any]) -> str:
    action = payload.get("action", {}) if isinstance(payload, dict) else {}
    if not isinstance(action, dict):
        return "unknown"
    subject_type = str(action.get("subject_type", "")).strip().lower()
    action_type = str(
        action.get("action_type")
        or action.get("Action_type")
        or action.get("type")
        or ""
    ).strip().lower()
    if subject_type and action_type:
        return f"{subject_type}_{action_type}"
    return action_type or subject_type or "unknown"


def event_summary(payload: dict[str, Any]) -> dict[str, str]:
    action = payload.get("action", {}) if isinstance(payload, dict) else {}
    if not isinstance(action, dict):
        action = {}
    subject = action.get("subject", {}) if isinstance(action.get("subject"), dict) else {}
    source = action.get("source", {}) if isinstance(action.get("source"), dict) else {}
    job_name = str(
        subject.get("name") or subject.get("subject") or action.get("name") or ""
    ).strip()
    job_number = str(
        subject.get("number")
        or subject.get("opportunity_number")
        or subject.get("reference")
        or ""
    ).strip()
    source_name = str(
        source.get("name")
        or source.get("description")
        or action.get("source_type")
        or ""
    ).strip()
    return {
        "event": event_name(payload),
        "action_id": str(action.get("id") or ""),
        "job": " · ".join(value for value in (job_number, job_name) if value),
        "source": source_name,
        "description": str(action.get("description") or "").strip(),
        "created_at": str(action.get("created_at") or ""),
    }


class CurrentRMSClient:
    def __init__(self, credentials: dict[str, str]):
        self.api_base = credentials["api_base"].rstrip("/")
        self.headers = {
            "X-SUBDOMAIN": credentials["subdomain"],
            "X-AUTH-TOKEN": credentials["api_key"],
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        response: requests.Response | None = None
        for attempt in range(8):
            response = requests.request(
                method,
                self.api_base + path,
                headers=self.headers,
                timeout=25,
                **kwargs,
            )
            if response.status_code != 429:
                break
            if attempt == 7:
                break
            reset = response.headers.get("X-RateLimit-Reset", "")
            retry_after = response.headers.get("Retry-After", "")
            try:
                delay = float(retry_after) if retry_after else float(reset) - time.time()
            except (TypeError, ValueError):
                delay = 60
            time.sleep(max(1, min(65, delay + 1)))
        assert response is not None
        if response.status_code >= 400:
            detail = response.text.strip()[:500]
            raise RuntimeError(
                f"Current RMS returned HTTP {response.status_code}"
                + (f": {detail}" if detail else "")
            )
        return response

    def list_webhooks(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for page in range(1, 100):
            response = self._request(
                "GET", "/webhooks", params={"page": page, "per_page": 100}
            )
            payload = response.json()
            hooks = payload.get("webhooks", []) if isinstance(payload, dict) else []
            page_items = [item for item in hooks if isinstance(item, dict)]
            results.extend(page_items)
            if len(page_items) < 100:
                break
        return results

    def create_webhook(self, event: str, target_url: str) -> dict[str, Any]:
        payload = {
            "webhook": {
                "name": f"{WEBHOOK_NAME_PREFIX} - {event}",
                "event": event,
                "target_url": target_url,
                "active": True,
            }
        }
        response = self._request("POST", "/webhooks", json=payload)
        result = response.json() if response.content else {}
        return result.get("webhook", result) if isinstance(result, dict) else {}

    def update_webhook(self, hook_id: Any, event: str, target_url: str) -> dict[str, Any]:
        payload = {
            "webhook": {
                "name": f"{WEBHOOK_NAME_PREFIX} - {event}",
                "event": event,
                "target_url": target_url,
                "active": True,
            }
        }
        response = self._request("PUT", f"/webhooks/{hook_id}", json=payload)
        result = response.json() if response.content else {}
        return result.get("webhook", result) if isinstance(result, dict) else {}

    def delete_webhook(self, hook_id: Any) -> None:
        self._request("DELETE", f"/webhooks/{hook_id}")


class EventStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = Lock()
        self.seen: set[str] = set()
        for record in self.read_recent(1000):
            identity = str(record.get("identity", ""))
            if identity:
                self.seen.add(identity)

    def read_recent(self, limit: int = 200) -> list[dict[str, Any]]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-limit:]
        except OSError:
            return []
        records = []
        for line in lines:
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                records.append(value)
        return records

    def append(self, identity: str, payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        from datetime import datetime

        with self.lock:
            duplicate = identity in self.seen
            record = {
                "received_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "identity": identity,
                "duplicate": duplicate,
                "summary": event_summary(payload),
                "payload": payload,
            }
            if not duplicate:
                self.seen.add(identity)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, separators=(",", ":")) + "\n")
            return duplicate, record


class AppSignals(QObject):
    receiver_event = Signal(object)
    receiver_status = Signal(str)
    tunnel_output = Signal(str)
    tunnel_ready = Signal(str)
    tunnel_error = Signal(str)
    task_success = Signal(str, object)
    task_error = Signal(str, str)


class ReceiverServer:
    def __init__(self, secret: str, store: EventStore, signals: AppSignals, config: dict[str, Any]):
        self.secret = secret
        self.store = store
        self.signals = signals
        self.config = config
        self.server = None
        self.thread: Thread | None = None
        app = Flask("warehouse-webhook-tester")
        app.logger.disabled = True

        @app.get("/health")
        def health():
            return jsonify({"ok": True, "application": "Warehouse Webhook Tester"})

        @app.post("/webhook/<provided_secret>")
        def receive(provided_secret: str):
            if not hmac.compare_digest(provided_secret, self.secret):
                return jsonify({"ok": False, "error": "invalid callback token"}), 404
            raw_body = request.get_data(cache=True)
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return jsonify({"ok": False, "error": "JSON object required"}), 400
            identity = event_identity(payload, raw_body)
            duplicate, record = self.store.append(identity, payload)
            self.signals.receiver_event.emit(record)
            if not duplicate and bool(self.config.get("forward_enabled")):
                forward_url = str(self.config.get("manager_forward_url") or "").strip()
                if forward_url:
                    Thread(target=self._forward_to_manager, args=(forward_url, payload), daemon=True).start()
            return jsonify({"ok": True, "duplicate": duplicate})

        self.app = app

    def _forward_to_manager(self, forward_url: str, payload: dict[str, Any]) -> None:
        last_error: Exception | None = None
        for attempt, delay in enumerate((0, 2, 5, 15, 30), start=1):
            if delay:
                time.sleep(delay)
            try:
                response = requests.post(forward_url, json=payload, timeout=8)
                response.raise_for_status()
                result = response.json() if response.content else {}
                if result.get("duplicate"):
                    self.signals.tunnel_output.emit("Manager Pi already received this webhook; duplicate ignored.")
                else:
                    self.signals.tunnel_output.emit("Webhook forwarded to the Manager Pi test screen.")
                return
            except Exception as error:
                last_error = error
                if attempt < 5:
                    continue
        self.signals.tunnel_output.emit(f"Manager Pi forwarding failed after retries: {last_error}")

    @property
    def running(self) -> bool:
        return bool(self.server and self.thread and self.thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self.server = make_server("127.0.0.1", LOCAL_PORT, self.app, threaded=True)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.signals.receiver_status.emit(
            f"Listening locally on http://127.0.0.1:{LOCAL_PORT}"
        )

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
        self.server = None


class TunnelController(QObject):
    def __init__(self, signals: AppSignals):
        super().__init__()
        self.signals = signals
        self.process: QProcess | None = None
        self.public_url = ""
        self._buffer = ""

    def start(self) -> None:
        if self.process and self.process.state() != QProcess.NotRunning:
            return
        if CLOUDFLARED_PATH.is_file():
            self._start_process()
            return
        self.signals.tunnel_output.emit("Downloading the Cloudflare quick-tunnel helper…")
        Thread(target=self._download, daemon=True).start()

    def _download(self) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            temporary = CLOUDFLARED_PATH.with_suffix(".download")
            with requests.get(CLOUDFLARED_DOWNLOAD_URL, stream=True, timeout=90) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
            os.replace(temporary, CLOUDFLARED_PATH)
        except Exception as error:
            self.signals.tunnel_error.emit(f"Could not download cloudflared: {error}")
            return
        self.signals.task_success.emit("cloudflared_downloaded", None)

    def _start_process(self) -> None:
        self.stop()
        self.public_url = ""
        self._buffer = ""
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_output)
        self.process.errorOccurred.connect(
            lambda _error: self.signals.tunnel_error.emit(self.process.errorString())
        )
        self.process.finished.connect(self._finished)
        self.process.start(
            str(CLOUDFLARED_PATH),
            ["tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{LOCAL_PORT}"],
        )
        self.signals.tunnel_output.emit("Starting temporary public HTTPS tunnel…")

    def _read_output(self) -> None:
        if not self.process:
            return
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._buffer = (self._buffer + text)[-12000:]
        for line in text.splitlines():
            if line.strip():
                self.signals.tunnel_output.emit(line.strip())
        match = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", self._buffer)
        if match and not self.public_url:
            self.public_url = match.group(0)
            self.signals.tunnel_ready.emit(self.public_url)

    def _finished(self, exit_code: int, _status: Any) -> None:
        if not self.public_url:
            self.signals.tunnel_error.emit(
                f"The tunnel stopped before producing a public URL (exit {exit_code})."
            )

    def stop(self) -> None:
        if self.process and self.process.state() != QProcess.NotRunning:
            self.process.terminate()
            if not self.process.waitForFinished(2500):
                self.process.kill()
                self.process.waitForFinished(1500)
        self.process = None
        self.public_url = ""


class MainWindow(QMainWindow):
    def __init__(self, auto_register: bool = False):
        super().__init__()
        self.setWindowTitle("Current RMS Warehouse Webhook Tester")
        self.resize(1180, 760)
        self.config = load_or_create_config()
        self.store = EventStore(EVENTS_PATH)
        self.signals = AppSignals()
        self.receiver = ReceiverServer(
            str(self.config["callback_secret"]), self.store, self.signals, self.config
        )
        self.tunnel = TunnelController(self.signals)
        self.credentials: dict[str, str] | None = None
        self.hooks: list[dict[str, Any]] = []
        self.custom_events = normalize_custom_events(self.config.get("custom_events"))
        self.config["custom_events"] = self.custom_events
        save_json(CONFIG_PATH, self.config)
        self.event_checks: dict[str, QCheckBox] = {}
        self.visibility_checks: dict[str, QCheckBox] = {}
        self.auto_register = auto_register
        self._auto_registration_started = False
        self._build_ui()
        self._connect_signals()
        self._load_credentials()
        self._load_recent_events()
        self.receiver.start()
        if auto_register:
            QTimer.singleShot(300, self.start_tunnel)

    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)

        title = QLabel("Current RMS Warehouse Webhook Tester")
        title.setStyleSheet("font-size: 24px; font-weight: 700;")
        subtitle = QLabel(
            "Receive, inspect and relay Current RMS warehouse events."
        )
        subtitle.setStyleSheet("color: #52606d;")
        outer.addWidget(title)
        outer.addWidget(subtitle)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setStyleSheet(
            "QTabBar::tab { min-width: 125px; padding: 10px 16px; font-weight: 600; }"
        )
        outer.addWidget(self.tabs, 1)

        connection_page = QWidget()
        connection_page_layout = QVBoxLayout(connection_page)
        connection_page_layout.setContentsMargins(10, 12, 10, 10)
        connection_page_layout.setSpacing(12)

        top_grid = QGridLayout()
        connection_group = QGroupBox("Current RMS connection")
        connection_form = QFormLayout(connection_group)
        self.settings_path = QLineEdit(str(SETTINGS_PATH))
        self.settings_path.setReadOnly(True)
        self.subdomain_label = QLabel("Not loaded")
        self.api_key_label = QLabel("Not loaded")
        self.api_status_label = QLabel("Waiting")
        reload_button = QPushButton("Reload Manager Pi settings")
        reload_button.clicked.connect(self._load_credentials)
        connection_form.addRow("Settings file", self.settings_path)
        connection_form.addRow("Subdomain", self.subdomain_label)
        connection_form.addRow("API key", self.api_key_label)
        connection_form.addRow("Status", self.api_status_label)
        connection_form.addRow("", reload_button)

        receiver_group = QGroupBox("Test receiver")
        receiver_form = QFormLayout(receiver_group)
        self.receiver_status_label = QLabel("Stopped")
        self.public_url = QLineEdit()
        self.public_url.setReadOnly(True)
        self.public_url.setPlaceholderText("Start the tunnel to obtain an HTTPS URL")
        self.tunnel_status_label = QLabel("Stopped")
        tunnel_buttons = QHBoxLayout()
        self.tunnel_button = QPushButton("Start HTTPS tunnel")
        self.tunnel_button.clicked.connect(self.start_tunnel)
        self.stop_tunnel_button = QPushButton("Stop tunnel")
        self.stop_tunnel_button.clicked.connect(self.stop_tunnel)
        tunnel_buttons.addWidget(self.tunnel_button)
        tunnel_buttons.addWidget(self.stop_tunnel_button)
        receiver_form.addRow("Local receiver", self.receiver_status_label)
        receiver_form.addRow("Public URL", self.public_url)
        receiver_form.addRow("Tunnel", self.tunnel_status_label)
        receiver_form.addRow("", tunnel_buttons)

        relay_group = QGroupBox("Manager Pi test-screen relay")
        relay_form = QFormLayout(relay_group)
        self.forward_enabled = QCheckBox("Forward received webhooks to the Manager Pi")
        self.forward_enabled.setChecked(bool(self.config.get("forward_enabled", False)))
        self.manager_forward_url = QLineEdit(str(self.config.get("manager_forward_url") or ""))
        self.manager_forward_url.setPlaceholderText(
            "Paste the Tester forwarding URL from Manager > Notifications"
        )
        self.relay_status_label = QLabel("Saved settings are used immediately")
        relay_buttons = QHBoxLayout()
        save_relay_button = QPushButton("Save relay settings")
        save_relay_button.clicked.connect(self.save_relay_settings)
        relay_buttons.addWidget(save_relay_button)
        relay_buttons.addStretch(1)
        relay_form.addRow("", self.forward_enabled)
        relay_form.addRow("Manager forwarding URL", self.manager_forward_url)
        relay_form.addRow("Status", self.relay_status_label)
        relay_form.addRow("", relay_buttons)

        top_grid.addWidget(connection_group, 0, 0)
        top_grid.addWidget(receiver_group, 0, 1)
        top_grid.addWidget(relay_group, 1, 0, 1, 2)
        top_grid.setColumnStretch(0, 1)
        top_grid.setColumnStretch(1, 1)
        connection_page_layout.addLayout(top_grid)
        connection_page_layout.addStretch(1)
        self.tabs.addTab(connection_page, "Connection + Relay")

        hooks_page = QWidget()
        hooks_page_layout = QVBoxLayout(hooks_page)
        hooks_page_layout.setContentsMargins(10, 12, 10, 10)
        hooks_page_layout.setSpacing(12)

        events_group = QGroupBox("Current RMS test webhooks")
        events_layout = QVBoxLayout(events_group)

        active_group = QGroupBox("Warehouse notification hooks")
        active_layout = QVBoxLayout(active_group)
        active_help = QLabel(
            "These nine events power the warehouse dashboard notifications and are selected by default."
        )
        active_help.setWordWrap(True)
        active_help.setStyleSheet("color: #52606d;")
        active_layout.addWidget(active_help)
        active_checks_widget = QWidget()
        self.active_registration_checks_layout = QGridLayout(active_checks_widget)
        self.active_registration_choice_slot = 0
        active_layout.addWidget(active_checks_widget)
        events_layout.addWidget(active_group)

        additional_group = QGroupBox("Additional Current RMS events")
        additional_layout = QVBoxLayout(additional_group)
        self.registration_search = QLineEdit()
        self.registration_search.setPlaceholderText(
            "Search additional webhook events"
        )
        self.registration_search.textChanged.connect(self.search_registration_choices)
        additional_layout.addWidget(self.registration_search)
        registration_checks_widget = QWidget()
        self.registration_checks_layout = QGridLayout(registration_checks_widget)
        self.registration_choice_slot = 0
        for event, label in self.event_definitions():
            self._add_registration_choice(event, label)
        registration_scroll = QScrollArea()
        registration_scroll.setWidgetResizable(True)
        registration_scroll.setWidget(registration_checks_widget)
        registration_scroll.setMinimumHeight(160)
        additional_layout.addWidget(registration_scroll)
        events_layout.addWidget(additional_group, 1)

        custom_group = QGroupBox("Add an event not listed in the official catalogue")
        custom_form = QFormLayout(custom_group)
        self.custom_preset = QComboBox()
        for preset_text, label, event in WAREHOUSE_EVENT_PRESETS:
            self.custom_preset.addItem(preset_text, (label, event))
        self.custom_preset.currentIndexChanged.connect(self.use_custom_preset)
        self.custom_label_input = QLineEdit()
        self.custom_label_input.setPlaceholderText("For example: Job booked out")
        self.custom_event_input = QLineEdit()
        self.custom_event_input.setPlaceholderText("For example: opportunity_book_out")
        add_custom_button = QPushButton("Add custom webhook choice")
        add_custom_button.clicked.connect(self.add_custom_event)
        custom_entry = QHBoxLayout()
        custom_entry.addWidget(self.custom_label_input, 2)
        custom_entry.addWidget(self.custom_event_input, 2)
        custom_entry.addWidget(add_custom_button)
        self.custom_remove_combo = QComboBox()
        remove_custom_button = QPushButton("Remove selected custom choice")
        remove_custom_button.clicked.connect(self.remove_custom_event)
        custom_remove = QHBoxLayout()
        custom_remove.addWidget(self.custom_remove_combo, 1)
        custom_remove.addWidget(remove_custom_button)
        custom_form.addRow("Warehouse example", self.custom_preset)
        custom_form.addRow("Name and event code", custom_entry)
        custom_form.addRow("Saved custom choices", custom_remove)
        custom_help = QLabel(
            "The complete documented catalogue is included above. Use this only for a new "
            "Current RMS event that is not yet in the official collection."
        )
        custom_help.setWordWrap(True)
        custom_help.setStyleSheet("color: #52606d;")
        custom_form.addRow("", custom_help)
        self._refresh_custom_remove_choices()
        hook_buttons = QHBoxLayout()
        self.list_hooks_button = QPushButton("Check existing webhooks")
        self.list_hooks_button.clicked.connect(self.refresh_hooks)
        self.register_button = QPushButton("Create/update selected test webhooks")
        self.register_button.clicked.connect(self.register_hooks)
        self.remove_button = QPushButton("Remove tester webhooks")
        self.remove_button.clicked.connect(self.confirm_remove_hooks)
        self.self_test_button = QPushButton("Send local sample event")
        self.self_test_button.clicked.connect(self.send_sample_event)
        hook_buttons.addWidget(self.list_hooks_button)
        hook_buttons.addWidget(self.register_button)
        hook_buttons.addWidget(self.remove_button)
        hook_buttons.addStretch(1)
        hook_buttons.addWidget(self.self_test_button)
        events_layout.addLayout(hook_buttons)
        self.hook_status_label = QLabel("No Current RMS changes have been made.")
        self.hook_status_label.setWordWrap(True)
        events_layout.addWidget(self.hook_status_label)
        hooks_page_layout.addWidget(events_group, 3)
        hooks_page_layout.addWidget(custom_group, 1)
        self.tabs.addTab(hooks_page, "Webhook Setup")

        received_page = QWidget()
        received_page_layout = QVBoxLayout(received_page)
        received_page_layout.setContentsMargins(10, 12, 10, 10)
        received_page_layout.setSpacing(8)

        received_help = QLabel(
            "Newest events appear first. Select a row to inspect the complete payload."
        )
        received_help.setStyleSheet("color: #52606d;")
        received_page_layout.addWidget(received_help)

        splitter = QSplitter(Qt.Horizontal)
        self.event_table = QTableWidget(0, 6)
        self.event_table.setHorizontalHeaderLabels(
            ["Received", "Event", "Job", "Item/source", "Action ID", "Duplicate"]
        )
        self.event_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.event_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.event_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.event_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.event_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.event_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.event_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.event_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.event_table.itemSelectionChanged.connect(self.show_selected_event)
        self.event_detail = QTextEdit()
        self.event_detail.setReadOnly(True)
        self.event_detail.setPlaceholderText("Select an event to inspect the complete JSON payload.")
        splitter.addWidget(self.event_table)
        splitter.addWidget(self.event_detail)
        splitter.setSizes([760, 400])
        received_page_layout.addWidget(splitter, 1)
        self.tabs.addTab(received_page, "Received Events")

        filters_page = QWidget()
        filters_page_layout = QVBoxLayout(filters_page)
        filters_page_layout.setContentsMargins(10, 12, 10, 10)

        filters_group = QGroupBox("Visible event types")
        filters_layout = QVBoxLayout(filters_group)
        filters_help = QLabel(
            "Uncheck an event to hide it from the list. Hidden events are still received and logged."
        )
        filters_help.setStyleSheet("color: #52606d;")
        filters_layout.addWidget(filters_help)
        self.visibility_search = QLineEdit()
        self.visibility_search.setPlaceholderText("Search visible-event filters")
        self.visibility_search.textChanged.connect(self.search_visibility_choices)
        filters_layout.addWidget(self.visibility_search)
        filter_checks_widget = QWidget()
        self.filter_checks_layout = QGridLayout(filter_checks_widget)
        self.filter_choice_slot = 0
        configured_visible = self.config.get("visible_events")
        if isinstance(configured_visible, list):
            visible_events = {str(value) for value in configured_visible}
            if int(self.config.get("catalogue_version", 0) or 0) < 1:
                visible_events.update(
                    event
                    for event, _label in DOCUMENTED_EVENTS
                    if event not in DEFAULT_EVENT_LABELS
                )
        else:
            visible_events = {event for event, _label in self.event_definitions()} | {"__other__"}
        self.config["catalogue_version"] = 1
        for event, label in self.event_definitions():
            self._add_visibility_choice(event, label, event in visible_events)
        other_checkbox = QCheckBox("Other / unknown")
        other_checkbox.setChecked("__other__" in visible_events)
        other_checkbox.stateChanged.connect(self.apply_event_filters)
        self.visibility_checks["__other__"] = other_checkbox
        other_index = self.filter_choice_slot
        self.filter_choice_slot += 1
        self.filter_checks_layout.addWidget(other_checkbox, other_index // 3, other_index % 3)
        filters_scroll = QScrollArea()
        filters_scroll.setWidgetResizable(True)
        filters_scroll.setWidget(filter_checks_widget)
        filters_layout.addWidget(filters_scroll)
        filter_footer = QHBoxLayout()
        show_all_button = QPushButton("Show all event types")
        show_all_button.clicked.connect(self.show_all_event_types)
        self.filter_status_label = QLabel("All event types visible")
        filter_footer.addWidget(show_all_button)
        filter_footer.addWidget(self.filter_status_label)
        filter_footer.addStretch(1)
        filters_layout.addLayout(filter_footer)
        filters_page_layout.addWidget(filters_group, 1)
        self.tabs.addTab(filters_page, "Display Filters")

        log_page = QWidget()
        log_page_layout = QVBoxLayout(log_page)
        log_page_layout.setContentsMargins(10, 12, 10, 10)
        log_help = QLabel(
            "Tunnel, relay and Current RMS registration messages appear here."
        )
        log_help.setStyleSheet("color: #52606d;")
        log_page_layout.addWidget(log_help)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("Tunnel and application messages appear here.")
        log_page_layout.addWidget(self.log_box, 1)
        self.tabs.addTab(log_page, "Activity Log")
        self.tabs.setCurrentIndex(0)
        self.setCentralWidget(central)

    def event_definitions(self) -> list[tuple[str, str]]:
        return list(DOCUMENTED_EVENTS) + [
            (item["event"], item["label"]) for item in self.custom_events
        ]

    def search_registration_choices(self, text: str) -> None:
        query = str(text).strip().lower()
        for event, checkbox in self.event_checks.items():
            if event in ACTIVE_NOTIFICATION_EVENTS:
                continue
            checkbox.setVisible(
                not query or query in event.lower() or query in checkbox.text().lower()
            )

    def search_visibility_choices(self, text: str) -> None:
        query = str(text).strip().lower()
        for event, checkbox in self.visibility_checks.items():
            checkbox.setVisible(
                not query or query in event.lower() or query in checkbox.text().lower()
            )

    def _add_registration_choice(self, event: str, label: str) -> None:
        checkbox = QCheckBox(f"{label}  ({event})")
        checkbox.setChecked(event in ACTIVE_NOTIFICATION_EVENTS)
        self.event_checks[event] = checkbox
        if event in ACTIVE_NOTIFICATION_EVENTS:
            index = self.active_registration_choice_slot
            self.active_registration_choice_slot += 1
            self.active_registration_checks_layout.addWidget(checkbox, index // 3, index % 3)
        else:
            index = self.registration_choice_slot
            self.registration_choice_slot += 1
            self.registration_checks_layout.addWidget(checkbox, index // 2, index % 2)

    def _add_visibility_choice(
        self, event: str, label: str, checked: bool = True
    ) -> None:
        checkbox = QCheckBox(label)
        checkbox.setChecked(checked)
        checkbox.stateChanged.connect(self.apply_event_filters)
        self.visibility_checks[event] = checkbox
        index = self.filter_choice_slot
        self.filter_choice_slot += 1
        self.filter_checks_layout.addWidget(checkbox, index // 3, index % 3)

    def _refresh_custom_remove_choices(self) -> None:
        self.custom_remove_combo.clear()
        if not self.custom_events:
            self.custom_remove_combo.addItem("No custom choices saved", "")
            return
        for item in self.custom_events:
            self.custom_remove_combo.addItem(
                f"{item['label']}  ({item['event']})", item["event"]
            )

    def use_custom_preset(self, index: int) -> None:
        data = self.custom_preset.itemData(index)
        if not isinstance(data, tuple) or len(data) != 2:
            return
        label, event = data
        if event:
            self.custom_label_input.setText(str(label))
            self.custom_event_input.setText(str(event))

    def add_custom_event(self) -> None:
        event = normalize_event_code(self.custom_event_input.text())
        label = self.custom_label_input.text().strip()
        if not CUSTOM_EVENT_PATTERN.fullmatch(event):
            self.hook_status_label.setText(
                "Enter a Current RMS event code such as opportunity_book_out."
            )
            return
        if event in self.event_checks:
            self.hook_status_label.setText(
                f"{event} is already available in the webhook choices."
            )
            return
        if not label:
            label = event.replace("_", " ").title()
        item = {"event": event, "label": label}
        self.custom_events.append(item)
        self.config["custom_events"] = self.custom_events
        self._add_registration_choice(event, label)
        self._add_visibility_choice(event, label)
        self.search_registration_choices(self.registration_search.text())
        self.search_visibility_choices(self.visibility_search.text())
        self._refresh_custom_remove_choices()
        self.custom_remove_combo.setCurrentIndex(self.custom_remove_combo.count() - 1)
        self.custom_preset.setCurrentIndex(0)
        self.custom_label_input.clear()
        self.custom_event_input.clear()
        self.apply_event_filters()
        self.hook_status_label.setText(
            f"Added {label}. Click Create/update selected test webhooks to register it."
        )

    def remove_custom_event(self) -> None:
        event = str(self.custom_remove_combo.currentData() or "")
        if not event:
            self.hook_status_label.setText("There is no custom choice to remove.")
            return
        self.custom_events = [
            item for item in self.custom_events if item.get("event") != event
        ]
        self.config["custom_events"] = self.custom_events
        registration = self.event_checks.pop(event, None)
        if registration is not None:
            self.registration_checks_layout.removeWidget(registration)
            registration.deleteLater()
        visibility = self.visibility_checks.pop(event, None)
        if visibility is not None:
            self.filter_checks_layout.removeWidget(visibility)
            visibility.deleteLater()
        self._refresh_custom_remove_choices()
        self.apply_event_filters()
        self.hook_status_label.setText(
            f"Removed {event} from the tester choices. Any webhook already registered "
            "in Current RMS has not been deleted."
        )

    def _connect_signals(self) -> None:
        self.signals.receiver_event.connect(self.add_event_record)
        self.signals.receiver_status.connect(self.receiver_status_label.setText)
        self.signals.tunnel_output.connect(self.append_log)
        self.signals.tunnel_ready.connect(self.tunnel_is_ready)
        self.signals.tunnel_error.connect(self.tunnel_failed)
        self.signals.task_success.connect(self.task_succeeded)
        self.signals.task_error.connect(self.task_failed)

    def _load_credentials(self) -> None:
        try:
            self.credentials = load_current_rms_credentials()
        except Exception as error:
            self.credentials = None
            self.api_status_label.setText(str(error))
            self.api_status_label.setStyleSheet("color: #b42318;")
            return
        self.subdomain_label.setText(self.credentials["subdomain"])
        self.api_key_label.setText(masked_key(self.credentials["api_key"]))
        self.api_status_label.setText("Loaded from Manager Pi settings")
        self.api_status_label.setStyleSheet("color: #067647;")

    def _load_recent_events(self) -> None:
        for record in self.store.read_recent(200):
            self.add_event_record(record, select=False)
        self.apply_event_filters()

    def selected_events(self) -> list[str]:
        return [event for event, checkbox in self.event_checks.items() if checkbox.isChecked()]

    def visible_events(self) -> set[str]:
        return {
            event
            for event, checkbox in self.visibility_checks.items()
            if checkbox.isChecked()
        }

    def record_is_visible(self, record: dict[str, Any]) -> bool:
        summary = record.get("summary", {}) if isinstance(record, dict) else {}
        event = str(summary.get("event", ""))
        filter_key = event if event in self.visibility_checks else "__other__"
        return filter_key in self.visible_events()

    def apply_event_filters(self) -> None:
        if not hasattr(self, "event_table"):
            return
        visible_count = 0
        hidden_count = 0
        for row in range(self.event_table.rowCount()):
            item = self.event_table.item(row, 0)
            record = item.data(Qt.UserRole) if item else None
            is_visible = isinstance(record, dict) and self.record_is_visible(record)
            self.event_table.setRowHidden(row, not is_visible)
            if is_visible:
                visible_count += 1
            else:
                hidden_count += 1
        self.config["visible_events"] = sorted(self.visible_events())
        save_json(CONFIG_PATH, self.config)
        if hasattr(self, "filter_status_label"):
            self.filter_status_label.setText(
                f"{visible_count} visible · {hidden_count} hidden"
            )
        current_row = self.event_table.currentRow()
        if current_row >= 0 and self.event_table.isRowHidden(current_row):
            self.event_table.clearSelection()
            self.event_detail.clear()

    def show_all_event_types(self) -> None:
        for checkbox in self.visibility_checks.values():
            checkbox.blockSignals(True)
            checkbox.setChecked(True)
            checkbox.blockSignals(False)
        self.apply_event_filters()

    def callback_url(self) -> str:
        public = self.public_url.text().strip().rstrip("/")
        secret = str(self.config["callback_secret"])
        return f"{public}/webhook/{secret}" if public else ""

    def save_relay_settings(self) -> None:
        forward_url = self.manager_forward_url.text().strip()
        enabled = self.forward_enabled.isChecked()
        if enabled and not forward_url:
            self.relay_status_label.setText("Paste the Manager Pi forwarding URL first.")
            self.relay_status_label.setStyleSheet("color: #b42318;")
            return
        if forward_url and not re.match(r"^https?://", forward_url, re.IGNORECASE):
            self.relay_status_label.setText("The forwarding URL must start with http:// or https://")
            self.relay_status_label.setStyleSheet("color: #b42318;")
            return
        self.config["forward_enabled"] = enabled
        self.config["manager_forward_url"] = forward_url
        save_json(CONFIG_PATH, self.config)
        self.relay_status_label.setText("Relay enabled" if enabled else "Relay disabled")
        self.relay_status_label.setStyleSheet("color: #067647;")

    def start_tunnel(self) -> None:
        self.receiver.start()
        self.tunnel_button.setEnabled(False)
        self.tunnel_status_label.setText("Starting…")
        self.tunnel.start()

    def stop_tunnel(self) -> None:
        self.tunnel.stop()
        self.public_url.clear()
        self.tunnel_status_label.setText("Stopped")
        self.tunnel_button.setEnabled(True)

    def tunnel_is_ready(self, url: str) -> None:
        self.public_url.setText(url)
        self.tunnel_status_label.setText("Online — keep this application open")
        self.tunnel_status_label.setStyleSheet("color: #067647;")
        self.tunnel_button.setEnabled(True)
        self.append_log(f"Public receiver ready: {url}")
        if self.auto_register and not self._auto_registration_started:
            self._auto_registration_started = True
            QTimer.singleShot(350, self.register_hooks)

    def tunnel_failed(self, message: str) -> None:
        self.tunnel_status_label.setText("Failed")
        self.tunnel_status_label.setStyleSheet("color: #b42318;")
        self.tunnel_button.setEnabled(True)
        self.append_log(message)

    def _run_task(self, name: str, operation: Callable[[], Any]) -> None:
        def worker() -> None:
            try:
                result = operation()
            except Exception as error:
                self.signals.task_error.emit(name, str(error))
            else:
                self.signals.task_success.emit(name, result)

        Thread(target=worker, daemon=True).start()

    def _client(self) -> CurrentRMSClient:
        if not self.credentials:
            raise RuntimeError("Load the Manager Pi Current RMS settings first.")
        return CurrentRMSClient(self.credentials)

    def refresh_hooks(self) -> None:
        self.hook_status_label.setText("Checking Current RMS webhooks…")
        self._run_task("list_hooks", lambda: self._client().list_webhooks())

    def register_hooks(self) -> None:
        callback_url = self.callback_url()
        events = self.selected_events()
        if not callback_url:
            self.hook_status_label.setText("Start the HTTPS tunnel before creating webhooks.")
            return
        if not events:
            self.hook_status_label.setText("Select at least one Current RMS event.")
            return
        self.register_button.setEnabled(False)
        self.hook_status_label.setText("Creating/updating tester webhooks in Current RMS…")

        def operation() -> dict[str, Any]:
            client = self._client()
            existing = client.list_webhooks()
            tester = {
                str(item.get("event", "")): item
                for item in existing
                if str(item.get("name", "")).startswith(WEBHOOK_NAME_PREFIX)
            }
            created: list[str] = []
            updated: list[str] = []
            unchanged: list[str] = []
            for event in events:
                hook = tester.get(event)
                if not hook:
                    client.create_webhook(event, callback_url)
                    created.append(event)
                elif (
                    str(hook.get("target_url", "")) != callback_url
                    or not bool(hook.get("active", False))
                ):
                    client.update_webhook(hook.get("id"), event, callback_url)
                    updated.append(event)
                else:
                    unchanged.append(event)
            return {
                "created": created,
                "updated": updated,
                "unchanged": unchanged,
                "hooks": client.list_webhooks(),
            }

        self._run_task("register_hooks", operation)

    def confirm_remove_hooks(self) -> None:
        answer = QMessageBox.question(
            self,
            "Remove tester webhooks",
            "Remove every Current RMS webhook whose name starts with "
            f"'{WEBHOOK_NAME_PREFIX}'? Existing non-tester webhooks will not be changed.",
        )
        if answer == QMessageBox.Yes:
            self.remove_hooks()

    def remove_hooks(self) -> None:
        self.remove_button.setEnabled(False)
        self.hook_status_label.setText("Removing tester webhooks…")

        def operation() -> dict[str, Any]:
            client = self._client()
            existing = client.list_webhooks()
            tester = [
                item
                for item in existing
                if str(item.get("name", "")).startswith(WEBHOOK_NAME_PREFIX)
            ]
            for hook in tester:
                client.delete_webhook(hook.get("id"))
            return {"removed": len(tester), "hooks": client.list_webhooks()}

        self._run_task("remove_hooks", operation)

    def task_succeeded(self, name: str, result: Any) -> None:
        if name == "cloudflared_downloaded":
            self.append_log("Tunnel helper downloaded.")
            self.tunnel._start_process()
            return
        if name == "sample_event":
            self.append_log(str(result))
            return
        if name == "list_hooks":
            self.hooks = list(result or [])
            tester_count = sum(
                1
                for item in self.hooks
                if str(item.get("name", "")).startswith(WEBHOOK_NAME_PREFIX)
            )
            self.hook_status_label.setText(
                f"Current RMS has {len(self.hooks)} webhook(s); "
                f"{tester_count} belong to this tester."
            )
            return
        if name == "register_hooks":
            result = result or {}
            self.hooks = list(result.get("hooks", []))
            created = len(result.get("created", []))
            updated = len(result.get("updated", []))
            unchanged = len(result.get("unchanged", []))
            self.register_button.setEnabled(True)
            self.hook_status_label.setText(
                f"Tester webhooks ready: {created} created, {updated} updated, "
                f"{unchanged} already correct. Keep this application open while testing."
            )
            self.append_log("Current RMS tester webhooks are active.")
            return
        if name == "remove_hooks":
            result = result or {}
            self.hooks = list(result.get("hooks", []))
            self.remove_button.setEnabled(True)
            self.hook_status_label.setText(
                f"Removed {int(result.get('removed', 0))} tester webhook(s)."
            )

    def task_failed(self, name: str, message: str) -> None:
        if name == "register_hooks":
            self.register_button.setEnabled(True)
        if name == "remove_hooks":
            self.remove_button.setEnabled(True)
        self.hook_status_label.setText(f"{name.replace('_', ' ').title()} failed: {message}")
        self.append_log(f"ERROR: {message}")

    def send_sample_event(self) -> None:
        sample = {
            "action": {
                "id": f"sample-{secrets.token_hex(4)}",
                "subject_id": 12345,
                "subject_type": "Opportunity",
                "source_id": 98765,
                "source_type": "OpportunityItem",
                "Action_type": "create_item",
                "name": "Webhook tester sample",
                "description": "A sample item was added",
                "subject": {
                    "id": 12345,
                    "number": "TEST-001",
                    "name": "Sample warehouse job",
                },
                "source": {
                    "id": 98765,
                    "name": "LED Screen 55 inch",
                    "quantity": 4,
                },
            }
        }

        def operation() -> str:
            url = (
                f"http://127.0.0.1:{LOCAL_PORT}/webhook/"
                f"{self.config['callback_secret']}"
            )
            response = requests.post(url, json=sample, timeout=5)
            response.raise_for_status()
            return "Sample event accepted by the local receiver."

        self._run_task("sample_event", operation)

    def add_event_record(self, record: dict[str, Any], select: bool = True) -> None:
        summary = record.get("summary", {}) if isinstance(record, dict) else {}
        row = 0
        self.event_table.insertRow(row)
        values = [
            str(record.get("received_at", "")),
            str(summary.get("event", "")),
            str(summary.get("job", "")),
            str(summary.get("source", "")),
            str(summary.get("action_id", "")),
            "Yes" if record.get("duplicate") else "No",
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setData(Qt.UserRole, record)
            if record.get("duplicate"):
                item.setForeground(QColor("#9a6700"))
            self.event_table.setItem(row, column, item)
        is_visible = self.record_is_visible(record)
        self.event_table.setRowHidden(row, not is_visible)
        if hasattr(self, "filter_status_label"):
            visible_count = sum(
                not self.event_table.isRowHidden(table_row)
                for table_row in range(self.event_table.rowCount())
            )
            self.filter_status_label.setText(
                f"{visible_count} visible · {self.event_table.rowCount() - visible_count} hidden"
            )
        if select and is_visible:
            self.event_table.selectRow(row)

    def show_selected_event(self) -> None:
        row = self.event_table.currentRow()
        item = self.event_table.item(row, 0) if row >= 0 else None
        record = item.data(Qt.UserRole) if item else None
        if isinstance(record, dict):
            self.event_detail.setPlainText(json.dumps(record, indent=2))

    def append_log(self, message: str) -> None:
        clean = str(message).strip()
        if clean:
            self.log_box.append(clean)

    def closeEvent(self, event: QCloseEvent) -> None:
        tester_hooks = [
            item
            for item in self.hooks
            if str(item.get("name", "")).startswith(WEBHOOK_NAME_PREFIX)
        ]
        if tester_hooks:
            answer = QMessageBox.question(
                self,
                "Tester webhooks are still active",
                "Current RMS tester webhooks are still registered. Closing the application "
                "will make their temporary URL unavailable. Close anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        self.tunnel.stop()
        self.receiver.stop()
        event.accept()


def main() -> int:
    parser = argparse.ArgumentParser(description="Current RMS warehouse webhook tester")
    parser.add_argument(
        "--auto-register",
        action="store_true",
        help="Start the tunnel and create/update the selected tester hooks automatically.",
    )
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Warehouse Webhook Tester")
    window = MainWindow(auto_register=args.auto_register)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

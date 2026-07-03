from copy import deepcopy
from datetime import datetime
from itertools import zip_longest
import os
import re
import shutil
import subprocess
import sys
from threading import Lock, RLock, Thread
from time import monotonic, sleep
import traceback

from app_version import CURRENT_VERSION
from manager_app.activity_log import ActivityLog
from manager_app.current_rms import ALL_DEPARTMENT_TARGET, NO_DEPARTMENT_TARGET, DashboardBuilder
from manager_app.email_alerts import alert_email_enabled, send_alert_email, send_test_email
from manager_app.security import security_status, set_admin_password
from manager_app.settings_store import PROJECT_ROOT, SettingsStore

OFFLINE_AFTER_SECONDS = 35
TRANSITIONAL_STATUS_SECONDS = 180
UPDATE_CHECK_CACHE_SECONDS = 300
SCREEN_NAMES = ("today", "tomorrow", "prep", "outstanding", "unreturned", "notifications", "quarantines")
MANAGER_UPDATE_STATUS_FILE = "/tmp/warehouse-manager-update-status.json"
MANAGER_UPDATE_LOG_FILE = "/tmp/warehouse-manager-update.log"
STATUS_LABELS = {
    "online": "Online",
    "display_restarting": "Display Restarting",
    "rebooting": "Rebooting",
    "renaming": "Renaming",
    "switching_screen": "Switching Screen",
    "viewer_starting": "Display Starting",
    "updating": "Updating",
    "update_failed": "Update Failed",
}
TRANSITIONAL_STATES = {"display_restarting", "rebooting", "renaming", "switching_screen", "viewer_starting", "updating"}
UPDATE_ALL_MANAGER_DELAY_SECONDS = 30
MAX_AUDIO_STATUS_AGE_SECONDS = 600


def parse_iso(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts))
    except Exception:
        return None


def version_parts(value):
    parts = []
    for part in re.split(r"[^0-9]+", str(value or "")):
        if part == "":
            continue
        try:
            parts.append(int(part))
        except Exception:
            parts.append(0)
    return tuple(parts)


def version_is_newer(candidate, current):
    candidate_parts = version_parts(candidate)
    current_parts = version_parts(current)
    if not candidate_parts or not current_parts:
        return False

    for candidate_part, current_part in zip_longest(candidate_parts, current_parts, fillvalue=0):
        if candidate_part > current_part:
            return True
        if candidate_part < current_part:
            return False
    return False


class ManagerState:
    def __init__(self, store=None):
        self.store = store or SettingsStore()
        self.activity = ActivityLog()
        self.lock = RLock()
        self.dashboard_lock = RLock()
        self.update_check_lock = Lock()
        self.settings = self.store.load_settings()
        self.devices = self.store.load_devices()
        self.commands = {}
        self.alerts = {device_id: [] for device_id in self.devices}
        self.dashboard = DashboardBuilder()
        self.update_status_checked_at = 0
        self.update_status = {
            "checked_at": "",
            "local_version": CURRENT_VERSION,
            "latest_version": CURRENT_VERSION,
            "manager_update_available": False,
            "message": "Update check has not run yet.",
            "error": "",
            "source": "local",
        }
        self.log_activity("Manager", "Manager app started.")

    def log_activity(self, category, message, level="info", details=None):
        return self.activity.append(category, message, level=level, details=details)

    def log_exception(self, category, message, error=None):
        trace = traceback.format_exc()
        suffix = f": {error}" if error else ""
        return self.log_activity(
            category,
            f"{message}{suffix}",
            level="error",
            details={"traceback": trace},
        )

    def list_activity(self, category="All", level="All", limit=500):
        return self.activity.list_entries(category=category, level=level, limit=limit)

    def clear_activity(self):
        self.activity.clear()
        self.log_activity("Manager", "Activity log cleared.")

    def get_update_status(self):
        with self.lock:
            return dict(self.update_status)

    def _run_git(self, args, timeout=20):
        startupinfo = None
        creationflags = 0
        if sys.platform.startswith("win"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        result = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
        if result.returncode != 0:
            error_text = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(error_text or f"git {' '.join(args)} failed")
        return (result.stdout or "").strip()

    def _latest_github_version(self):
        if not (PROJECT_ROOT / ".git").exists():
            raise RuntimeError("This manager folder is not a Git clone.")

        upstream = self._run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], timeout=10)
        try:
            self._run_git(["fetch", "--quiet"], timeout=30)
        except Exception as error:
            self.log_activity("Updates", f"Could not refresh GitHub update information: {error}", level="warning")

        latest = self._run_git(["show", f"{upstream}:version.txt"], timeout=10).strip()
        if not latest:
            raise RuntimeError("GitHub version.txt was empty.")
        return latest

    def refresh_update_status(self, force=False):
        now_monotonic = monotonic()
        with self.lock:
            cached = dict(self.update_status)
            if not force and now_monotonic - self.update_status_checked_at < UPDATE_CHECK_CACHE_SECONDS:
                return cached

        if not self.update_check_lock.acquire(blocking=False):
            return self.get_update_status()

        try:
            checked_at = datetime.now().isoformat(timespec="seconds")
            status = {
                "checked_at": checked_at,
                "local_version": CURRENT_VERSION,
                "latest_version": CURRENT_VERSION,
                "manager_update_available": False,
                "message": "The manager is on the latest known version.",
                "error": "",
                "source": "local",
            }
            try:
                latest = self._latest_github_version()
                status["latest_version"] = latest
                status["source"] = "github"
                if version_is_newer(latest, CURRENT_VERSION):
                    status["manager_update_available"] = True
                    status["message"] = f"GitHub has version {latest}; this manager is running {CURRENT_VERSION}."
                else:
                    status["message"] = f"GitHub latest version is {latest}."
            except Exception as error:
                status["error"] = str(error)
                status["message"] = f"Could not check GitHub updates: {error}"

            with self.lock:
                previous = dict(self.update_status)
                self.update_status = status
                self.update_status_checked_at = monotonic()

            if status.get("error"):
                self.log_activity("Updates", status["message"], level="warning")
            elif status.get("latest_version") != previous.get("latest_version") or force:
                self.log_activity("Updates", status["message"])
            return dict(status)
        finally:
            self.update_check_lock.release()

    def _manager_pi_ready(self):
        return sys.platform.startswith("linux") and (PROJECT_ROOT / "scripts" / "install_manager_pi.sh").is_file()

    def _service_state(self, service_name):
        systemctl = shutil.which("systemctl")
        if not systemctl or not sys.platform.startswith("linux"):
            return "Unavailable"
        try:
            result = subprocess.run(
                [systemctl, "is-active", service_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
                check=False,
            )
            value = (result.stdout or "").strip()
            return value or "unknown"
        except Exception:
            return "unknown"

    def _read_json_file(self, path):
        try:
            import json

            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _read_log_tail(self, path, max_lines=80):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                lines = handle.readlines()
            return "".join(lines[-max_lines:]).strip()
        except Exception:
            return ""

    def get_manager_status(self):
        update_status = self.get_update_status()
        return {
            "version": CURRENT_VERSION,
            "is_manager_pi": self._manager_pi_ready(),
            "backend_service": self._service_state("warehouse-manager-backend.service"),
            "display_service": self._service_state("warehouse-manager-display.service"),
            "update_service": self._service_state("warehouse-manager-update.service"),
            "update_status": update_status,
            "manager_update_status": self._read_json_file(MANAGER_UPDATE_STATUS_FILE),
            "manager_update_log": self._read_log_tail(MANAGER_UPDATE_LOG_FILE),
            "security": security_status(),
        }

    def change_admin_password(self, current_password, new_password):
        status = set_admin_password(current_password, new_password)
        self.log_activity("Manager", "Manager Pi password changed.")
        return status

    def _sudo_prefix(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            return []
        sudo = shutil.which("sudo")
        if not sudo:
            raise RuntimeError("sudo is not available on this manager.")
        return [sudo, "-n"]

    def _run_manager_control(self, action, command, message):
        if not self._manager_pi_ready():
            raise RuntimeError("Manager Pi controls are only available when connected to a Manager Pi backend.")

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(detail or f"{action} failed with exit code {result.returncode}.")
        self.log_activity("Manager", message, details={"action": action})
        return {"ok": True, "action": action, "message": message}

    def _start_delayed_manager_update(self, delay_seconds=UPDATE_ALL_MANAGER_DELAY_SECONDS):
        def worker():
            if delay_seconds > 0:
                sleep(delay_seconds)
            try:
                self.run_manager_command("update")
            except Exception as error:
                self.log_exception("Manager", "Delayed Manager Pi update failed", error)

        Thread(target=worker, daemon=True).start()

    def run_manager_command(self, action):
        action = str(action or "").strip().lower()
        if action == "check_updates":
            status = self.refresh_update_status(force=True)
            return {"ok": True, "action": action, "message": "Checked GitHub for Manager Pi updates.", "status": status}

        if not self._manager_pi_ready():
            raise RuntimeError("Manager Pi controls are only available when connected to a Manager Pi backend.")

        if action == "update_all":
            with self.lock:
                device_ids = sorted(str(device_id) for device_id in self.devices.keys() if str(device_id).strip())
            if device_ids:
                self.queue_command(device_ids, "update")
            delay_seconds = UPDATE_ALL_MANAGER_DELAY_SECONDS if device_ids else 0
            self._start_delayed_manager_update(delay_seconds)
            message = (
                f"Queued GitHub update for {len(device_ids)} dashboard Pi screen(s). "
                f"Manager Pi update will start {'now' if delay_seconds == 0 else f'in {delay_seconds} seconds'}."
            )
            self.log_activity(
                "Updates",
                message,
                details={"device_ids": device_ids, "manager_delay_seconds": delay_seconds},
            )
            return {
                "ok": True,
                "action": action,
                "message": message,
                "device_count": len(device_ids),
                "manager_delay_seconds": delay_seconds,
            }

        systemctl = "/usr/bin/systemctl" if os.path.exists("/usr/bin/systemctl") else (shutil.which("systemctl") or "/usr/bin/systemctl")
        reboot = "/usr/sbin/reboot" if os.path.exists("/usr/sbin/reboot") else (shutil.which("reboot") or "/usr/sbin/reboot")
        sudo = self._sudo_prefix()

        commands = {
            "update": (
                sudo + [systemctl, "--no-block", "start", "warehouse-manager-update.service"],
                "Started Manager Pi update from GitHub.",
            ),
            "restart_backend": (
                sudo + [systemctl, "--no-block", "restart", "warehouse-manager-backend.service"],
                "Restarting Manager Pi backend service.",
            ),
            "restart_display": (
                sudo + [systemctl, "--no-block", "restart", "warehouse-manager-display.service"],
                "Restarting Manager Pi status display.",
            ),
            "reboot": (
                sudo + [reboot],
                "Rebooting Manager Pi.",
            ),
        }
        if action not in commands:
            raise RuntimeError(f"Unsupported Manager Pi action: {action}")

        command, message = commands[action]
        return self._run_manager_control(action, command, message)

    def get_settings(self, include_secret=False):
        with self.lock:
            settings = self.store.load_settings()
            self.settings = settings
            if include_secret:
                return settings

            sanitized = {
                "server": dict(settings.get("server", {})),
                "current_rms": dict(settings.get("current_rms", {})),
            }
            api_key = sanitized["current_rms"].get("api_key", "")
            sanitized["current_rms"]["api_key"] = "*" * min(len(api_key), 10) if api_key else ""
            return sanitized

    def save_settings(self, updates):
        with self.lock:
            merged = self.store.load_settings()
            for section, values in (updates or {}).items():
                if isinstance(values, dict) and isinstance(merged.get(section), dict):
                    merged[section].update(values)
                else:
                    merged[section] = values
            self.settings = self.store.save_settings(merged)
        with self.dashboard_lock:
            self.dashboard.refresh()
        sections = ", ".join(sorted(str(key) for key in (updates or {}).keys())) or "settings"
        self.log_activity("Settings", f"Saved {sections} settings.")
        return self.settings

    def test_current_rms(self, api_settings=None):
        with self.lock:
            settings = self.store.load_settings()
            if api_settings:
                settings.setdefault("current_rms", {}).update(api_settings)
        self.log_activity("Current RMS", "Testing Current RMS connection.")
        success, message = self.dashboard.test_connection(settings)
        self.log_activity(
            "Current RMS",
            message,
            level="info" if success else "error",
        )
        return success, message

    def test_email_alerts(self, alerts_settings=None):
        with self.lock:
            settings = self.store.load_settings()
            if alerts_settings:
                settings.setdefault("alerts", {}).update(alerts_settings)
        self.log_activity("Email", "Sending SMTP test email.")
        success, message = send_test_email(settings)
        self.log_activity("Email", message, level="info" if success else "error")
        return success, message

    def _remove_legacy_device(self, legacy_id, device_id):
        if legacy_id and legacy_id != device_id:
            removed_device = self.devices.pop(legacy_id, None)
            removed_alerts = self.alerts.pop(legacy_id, None)
            removed_command = self.commands.pop(legacy_id, None)
            if removed_device is not None or removed_alerts is not None or removed_command is not None:
                self.log_activity(
                    "Pis",
                    f"Removed legacy device row {legacy_id} after {device_id} re-registered.",
                )

    def _merge_device_identity(self, existing, payload, remote_addr, now):
        existing.update(
            {
                "id": payload.get("id") or existing.get("id") or "",
                "name": payload.get("name") or existing.get("name") or payload.get("id") or "",
                "screen": payload.get("screen") or existing.get("screen") or "today",
                "version": payload.get("version") or existing.get("version") or "",
                "display_scale": payload.get("display_scale") or existing.get("display_scale") or 100,
                "compact_layout": payload.get("compact_layout") or existing.get("compact_layout") or "auto",
                "ip": remote_addr or existing.get("ip") or "",
                "last_seen": now,
            }
        )
        audio_status = payload.get("audio_status")
        if isinstance(audio_status, dict):
            existing["audio_status"] = audio_status
            existing["audio_checked_at"] = now

    def _apply_status_update(self, existing, payload, now):
        state = str(payload.get("state", "")).strip()
        if not state:
            return
        message = str(payload.get("message", "")).strip() or STATUS_LABELS.get(state, state.replace("_", " ").title())
        source = str(payload.get("source", "")).strip() or "agent"
        existing["status_state"] = state
        existing["status_message"] = message
        existing["status_source"] = source
        existing["status_updated_at"] = now

    def register_device(self, payload, remote_addr):
        device_id = str(payload.get("id", "")).strip()
        if not device_id:
            return None
        legacy_id = str(payload.get("legacy_id", "")).strip()

        now = datetime.now().isoformat(timespec="seconds")
        with self.lock:
            self._remove_legacy_device(legacy_id, device_id)
            existing = self.devices.get(device_id, {})
            before = dict(existing)
            self._merge_device_identity(existing, payload, remote_addr, now)
            self._apply_status_update(existing, payload, now)
            self.devices[device_id] = existing
            self.alerts.setdefault(device_id, [])
            self.store.save_devices(self.devices)
            result = dict(existing)

        if not before:
            self.log_activity(
                "Pis",
                f"{result.get('name') or device_id} registered from {result.get('ip') or 'unknown IP'}.",
                details={"device_id": device_id, "version": result.get("version"), "screen": result.get("screen")},
            )
        elif any(before.get(key) != result.get(key) for key in ("name", "ip", "version")):
            self.log_activity(
                "Pis",
                f"{result.get('name') or device_id} updated registration details.",
                details={
                    "device_id": device_id,
                    "ip": result.get("ip"),
                    "version": result.get("version"),
                },
            )
        return result

    def report_device_status(self, payload, remote_addr):
        device_id = str(payload.get("id", "")).strip()
        if not device_id:
            return None
        legacy_id = str(payload.get("legacy_id", "")).strip()
        event_only = bool(payload.get("event_only"))
        source = str(payload.get("source", "")).strip() or "agent"
        message = str(payload.get("message", "")).strip()

        now = datetime.now().isoformat(timespec="seconds")
        with self.lock:
            self._remove_legacy_device(legacy_id, device_id)
            existing = self.devices.get(device_id, {})
            previous_state = str(existing.get("status_state", "")).strip()
            previous_message = str(existing.get("status_message", "")).strip()
            self._merge_device_identity(existing, payload, remote_addr, now)
            if not event_only:
                self._apply_status_update(existing, payload, now)
            self.devices[device_id] = existing
            self.alerts.setdefault(device_id, [])
            self.store.save_devices(self.devices)
            result = dict(existing)

        if event_only:
            category = "Audio" if source == "audio" else "Pis"
            level = str(payload.get("level", "")).strip().lower() or "info"
            if level not in {"info", "warning", "error"}:
                level = "info"
            self.log_activity(
                category,
                f"{result.get('name') or device_id}: {message or 'Event received.'}",
                level=level,
                details={"device_id": device_id, "source": source, "audio_status": payload.get("audio_status")},
            )
            return result

        state = str(result.get("status_state", "")).strip()
        message = str(result.get("status_message", "")).strip()
        if state and (state != previous_state or message != previous_message):
            category = "Updates" if state == "updating" else "Pis"
            self.log_activity(
                category,
                f"{result.get('name') or device_id}: {STATUS_LABELS.get(state, state.replace('_', ' ').title())}.",
                details={"device_id": device_id, "message": message, "source": result.get("status_source")},
            )
        return result

    def list_devices(self):
        state_events = []
        should_save = False
        with self.lock:
            now = datetime.now()
            update_status = dict(self.update_status)
            latest_version = str(update_status.get("latest_version") or CURRENT_VERSION).strip()
            devices = []
            for raw in self.devices.values():
                item = dict(raw)
                last_seen_dt = parse_iso(item.get("last_seen"))
                status_updated_dt = parse_iso(item.get("status_updated_at")) or last_seen_dt
                status_state = str(item.get("status_state", "")).strip() or "online"
                status_message = str(item.get("status_message", "")).strip()
                stale_seconds = None
                status_age_seconds = None
                if last_seen_dt:
                    stale_seconds = max(0, int((now - last_seen_dt).total_seconds()))
                if status_updated_dt:
                    status_age_seconds = max(0, int((now - status_updated_dt).total_seconds()))

                transition_is_current = (
                    status_state in TRANSITIONAL_STATES
                    and status_age_seconds is not None
                    and status_age_seconds <= TRANSITIONAL_STATUS_SECONDS
                )
                if status_state in TRANSITIONAL_STATES and not transition_is_current:
                    status_state = "online"
                    status_message = "Heartbeat active."

                if stale_seconds is None:
                    display_state = "Unknown"
                elif stale_seconds <= OFFLINE_AFTER_SECONDS:
                    display_state = STATUS_LABELS.get(status_state, status_state.replace("_", " ").title())
                elif transition_is_current:
                    display_state = STATUS_LABELS.get(status_state, status_state.replace("_", " ").title())
                else:
                    display_state = "Offline"

                if display_state == "Offline":
                    status_message = f"No heartbeat for {stale_seconds}s." if stale_seconds is not None else "No heartbeat received."
                elif not status_message:
                    status_message = "Heartbeat active."

                audio_status = item.get("audio_status", {}) if isinstance(item.get("audio_status", {}), dict) else {}
                audio_checked_dt = parse_iso(item.get("audio_checked_at"))
                audio_age_seconds = None
                if audio_checked_dt:
                    audio_age_seconds = max(0, int((now - audio_checked_dt).total_seconds()))
                if not audio_status:
                    item["audio"] = "Not checked"
                    item["audio_detail"] = "No sound check has been reported yet."
                elif audio_age_seconds is not None and audio_age_seconds > MAX_AUDIO_STATUS_AGE_SECONDS:
                    item["audio"] = "Check stale"
                    item["audio_detail"] = str(audio_status.get("summary") or "Last audio check is stale.")
                elif audio_status.get("ok"):
                    item["audio"] = "Audio OK"
                    item["audio_detail"] = str(audio_status.get("detail") or audio_status.get("summary") or "Audio OK.")
                else:
                    item["audio"] = "Audio Issue"
                    item["audio_detail"] = str(audio_status.get("summary") or audio_status.get("detail") or "Audio check failed.")
                item["audio_checked_at"] = item.get("audio_checked_at", "")

                if status_updated_dt:
                    status_message = f"{status_message} ({status_updated_dt.strftime('%d/%m/%Y %H:%M:%S')})"

                item["state"] = display_state
                item["activity"] = status_message
                device_version = str(item.get("version", "")).strip()
                if device_version and latest_version and version_is_newer(latest_version, device_version):
                    item["update"] = f"Available {latest_version}"
                elif device_version:
                    item["update"] = "Current"
                else:
                    item["update"] = "Unknown"
                previous_display_state = str(raw.get("last_display_state", "")).strip()
                if display_state and display_state != previous_display_state:
                    raw["last_display_state"] = display_state
                    should_save = True
                    state_events.append(
                        {
                            "category": "Updates" if display_state == "Updating" else "Pis",
                            "message": f"{item.get('name') or item.get('id')}: {display_state}.",
                            "details": {"device_id": item.get("id"), "activity": status_message},
                        }
                    )
                devices.append(item)

            if should_save:
                self.store.save_devices(self.devices)

        for event in state_events:
            self.log_activity(event["category"], event["message"], details=event["details"])

        return sorted(
            devices,
            key=lambda item: (item.get("name", item.get("id", "")), item.get("id", "")),
        )

    def queue_command(self, device_ids, action, **extra):
        command = {"action": action}
        command.update({key: value for key, value in extra.items() if value not in (None, "")})

        with self.lock:
            for device_id in device_ids:
                self.commands[str(device_id)] = dict(command)
        self.log_activity(
            "Commands",
            f"Queued {action} for {len(device_ids)} Pi screen(s).",
            details={"device_ids": [str(device_id) for device_id in device_ids], "command": command},
        )
        return command

    def remove_devices(self, device_ids):
        clean_ids = [str(device_id).strip() for device_id in (device_ids or []) if str(device_id).strip()]
        if not clean_ids:
            return 0

        removed = []
        with self.lock:
            for device_id in clean_ids:
                device = self.devices.pop(device_id, None)
                self.commands.pop(device_id, None)
                self.alerts.pop(device_id, None)
                if device is not None:
                    removed.append(device_id)

            if removed:
                self.store.save_devices(self.devices)

        if removed:
            self.log_activity(
                "Pis",
                f"Removed {len(removed)} Pi screen(s) from the manager list.",
                details={"device_ids": removed},
            )
        return len(removed)

    def poll_command(self, device_id):
        with self.lock:
            command = self.commands.pop(str(device_id), None)
        if command:
            self.log_activity(
                "Commands",
                f"Pi {device_id} collected command {command.get('action')}.",
                details={"device_id": str(device_id), "command": command},
            )
        return command

    def poll_alert(self, device_id):
        with self.lock:
            queue = self.alerts.setdefault(str(device_id), [])
            if not queue:
                return None
            alert = dict(queue.pop())
            alert["queue_remaining"] = len(queue)
        self.log_activity(
            "Notifications",
            f"Sent notification to Pi {device_id}: {alert.get('title') or alert.get('type') or 'Notification'}.",
            details={"device_id": str(device_id), "queue_remaining": alert.get("queue_remaining")},
        )
        return alert

    def clear_device_alerts(self, device_id):
        device_id = str(device_id or "").strip()
        if not device_id:
            return 0
        with self.lock:
            queue = self.alerts.setdefault(device_id, [])
            cleared = len(queue)
            queue.clear()
        if cleared:
            self.log_activity(
                "Notifications",
                f"Cleared {cleared} queued notification(s) for Pi {device_id}.",
                details={"device_id": device_id, "cleared": cleared},
            )
        return cleared

    def screen_payload(self, screen):
        with self.lock:
            settings = self.store.load_settings()
            self.settings = settings
        with self.dashboard_lock:
            payload = deepcopy(self.dashboard.build(screen, settings))
        return payload

    def all_screen_payloads(self):
        with self.lock:
            settings = self.store.load_settings()
            self.settings = settings
        with self.dashboard_lock:
            return {
                screen: deepcopy(self.dashboard.build(screen, settings))
                for screen in SCREEN_NAMES
            }

    def _normalise_route_value(self, value):
        return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())

    def _route_targets_to_device_ids(self, route_targets, devices):
        if isinstance(route_targets, str):
            route_targets = [item.strip() for item in route_targets.split(",") if item.strip()]
        if not isinstance(route_targets, list):
            route_targets = []

        target_terms = {
            self._normalise_route_value(item)
            for item in route_targets
            if self._normalise_route_value(item)
        }
        if not target_terms:
            return []

        matched_ids = []
        for device_id, device in devices.items():
            exact_values = [
                device_id,
                device.get("id", ""),
            ]
            fuzzy_values = [
                device.get("name", ""),
                device.get("screen", ""),
            ]
            exact_terms = [self._normalise_route_value(value) for value in exact_values if str(value).strip()]
            fuzzy_terms = [self._normalise_route_value(value) for value in fuzzy_values if str(value).strip()]
            if any(route_term == device_term for route_term in target_terms for device_term in exact_terms):
                matched_ids.append(str(device_id))
                continue
            if any(
                route_term == device_term or route_term in device_term or device_term in route_term
                for route_term in target_terms
                for device_term in fuzzy_terms
            ):
                matched_ids.append(str(device_id))

        return matched_ids

    def _event_target_device_ids(self, alert, devices, settings):
        device_ids = [str(device_id) for device_id in devices.keys() if str(device_id).strip()]
        event_routes = settings.get("alerts", {}).get("event_routes", {})
        if not isinstance(event_routes, dict):
            return device_ids

        event_type = str(alert.get("type", "")).strip()
        if event_type not in event_routes:
            return device_ids

        return self._route_targets_to_device_ids(event_routes.get(event_type, []), devices)

    def _alert_target_device_ids(self, alert, devices, settings):
        device_ids = self._event_target_device_ids(alert, devices, settings)
        has_department_filter = "target_departments" in alert
        departments = [
            str(item).strip()
            for item in (alert.get("target_departments") or [])
            if str(item).strip()
        ]
        if not departments:
            return [] if has_department_filter else device_ids
        if ALL_DEPARTMENT_TARGET in departments:
            return device_ids
        if NO_DEPARTMENT_TARGET in departments:
            return []

        routing = settings.get("alerts", {}).get("department_routing", {}) or {}
        routes = routing.get("routes", {}) if isinstance(routing.get("routes", {}), dict) else {}
        department_targets = []
        for department in departments:
            department_key = self._normalise_route_value(department)
            for route_department, configured_targets in routes.items():
                if self._normalise_route_value(route_department) != department_key:
                    continue
                if isinstance(configured_targets, str):
                    configured_targets = [item.strip() for item in configured_targets.split(",") if item.strip()]
                if isinstance(configured_targets, list):
                    department_targets.extend(configured_targets)

        department_ids = self._route_targets_to_device_ids(department_targets, devices)
        return [device_id for device_id in device_ids if device_id in set(department_ids)]

    def _send_alert_emails(self, alerts, settings):
        sent_count = 0
        failed_count = 0
        for alert in alerts or []:
            if not alert or not alert_email_enabled(settings, alert):
                continue
            success, message = send_alert_email(settings, alert)
            title = alert.get("title") or alert.get("type") or "Warehouse Alert"
            if success:
                sent_count += 1
                self.log_activity("Email", f"Sent email for alert: {title}.", details={"message": message})
            else:
                failed_count += 1
                self.log_activity("Email", f"Email failed for alert {title}: {message}", level="error")
        return sent_count, failed_count

    def refresh_dashboard(self):
        with self.lock:
            settings = self.store.load_settings()
            self.settings = settings
        started = monotonic()
        self.log_activity("Current RMS", "Refresh started.")
        try:
            with self.dashboard_lock:
                _, new_alerts = self.dashboard.refresh_data(settings)
                last_error = str(getattr(self.dashboard, "_last_error", "") or "").strip()
        except Exception as error:
            elapsed_ms = int((monotonic() - started) * 1000)
            self.log_exception("Current RMS", f"Refresh crashed after {elapsed_ms}ms", error)
            return
        elapsed_ms = int((monotonic() - started) * 1000)
        if last_error:
            self.log_activity(
                "Current RMS",
                f"Refresh failed after {elapsed_ms}ms: {last_error}",
                level="error",
            )
        else:
            self.log_activity(
                "Current RMS",
                f"Refresh finished in {elapsed_ms}ms.",
                details={"alerts_detected": len(new_alerts or [])},
            )
        if not new_alerts:
            return

        self._send_alert_emails(new_alerts, settings)

        deliverable = [
            alert
            for alert in new_alerts
            if alert and (alert.get("show_popup") or alert.get("play_sound"))
        ]
        if not deliverable:
            self.log_activity(
                "Notifications",
                f"{len(new_alerts)} alert event(s) detected but none were deliverable by current settings.",
            )
            return

        queued_count = 0
        target_ids = set()
        delivery_details = []
        with self.lock:
            for alert in deliverable:
                device_ids = self._alert_target_device_ids(alert, self.devices, settings)
                delivery_details.append(
                    {
                        "type": alert.get("type"),
                        "title": alert.get("title") or alert.get("type") or "Notification",
                        "target_departments": alert.get("target_departments", []),
                        "target_ids": sorted(device_ids),
                    }
                )
                for device_id in device_ids:
                    queue = self.alerts.setdefault(str(device_id), [])
                    queue.append(dict(alert))
                    target_ids.add(str(device_id))
                    queued_count += 1
        delivery_label = "delivery" if queued_count == 1 else "deliveries"
        self.log_activity(
            "Notifications",
            f"Queued {queued_count} notification {delivery_label} for {len(target_ids)} Pi screen(s).",
            details={
                "notifications": delivery_details,
                "target_ids": sorted(target_ids),
            },
        )

    def send_test_notification(self, title, message, sound_name="", play_sound=True, device_ids=None):
        with self.lock:
            settings = self.store.load_settings()
            self.settings = settings
            target_ids = [str(device_id) for device_id in (device_ids or self.devices.keys()) if str(device_id)]

        if not target_ids:
            self.log_activity("Notifications", "Test notification failed because no Pis are registered.", level="warning")
            return False, "No Pi screens are registered yet."

        with self.dashboard_lock:
            alert = self.dashboard.create_manual_alert(
                title=title,
                message=message,
                settings=settings,
                sound_name=sound_name,
                play_sound=play_sound,
            )

        if not alert:
            self.log_activity("Notifications", "Test notification failed because the message was empty.", level="warning")
            return False, "Enter some notification text first."

        with self.lock:
            for device_id in target_ids:
                queue = self.alerts.setdefault(str(device_id), [])
                queue.append(dict(alert))

        self.log_activity(
            "Notifications",
            f"Queued test notification for {len(target_ids)} Pi screen(s): {alert.get('title')}.",
            details={"device_ids": target_ids, "play_sound": alert.get("play_sound"), "sound": alert.get("sound")},
        )
        return True, f"Queued a test notification for {len(target_ids)} Pi screen(s)."

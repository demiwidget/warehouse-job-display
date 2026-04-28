from datetime import datetime
from threading import RLock

from manager_app.current_rms import DashboardBuilder
from manager_app.settings_store import SettingsStore


class ManagerState:
    def __init__(self, store=None):
        self.store = store or SettingsStore()
        self.lock = RLock()
        self.dashboard_lock = RLock()
        self.settings = self.store.load_settings()
        self.devices = self.store.load_devices()
        self.commands = {}
        self.alerts = {device_id: [] for device_id in self.devices}
        self.dashboard = DashboardBuilder()

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
        return self.settings

    def test_current_rms(self, api_settings=None):
        with self.lock:
            settings = self.store.load_settings()
            if api_settings:
                settings.setdefault("current_rms", {}).update(api_settings)
        return self.dashboard.test_connection(settings)

    def register_device(self, payload, remote_addr):
        device_id = str(payload.get("id", "")).strip()
        if not device_id:
            return None
        legacy_id = str(payload.get("legacy_id", "")).strip()

        now = datetime.now().isoformat(timespec="seconds")
        with self.lock:
            if legacy_id and legacy_id != device_id:
                self.devices.pop(legacy_id, None)
                self.alerts.pop(legacy_id, None)
                self.commands.pop(legacy_id, None)
            existing = self.devices.get(device_id, {})
            existing.update(
                {
                    "id": device_id,
                    "name": payload.get("name") or existing.get("name") or device_id,
                    "screen": payload.get("screen") or existing.get("screen") or "today",
                    "version": payload.get("version") or existing.get("version") or "",
                    "ip": remote_addr or existing.get("ip") or "",
                    "last_seen": now,
                }
            )
            self.devices[device_id] = existing
            self.alerts.setdefault(device_id, [])
            self.store.save_devices(self.devices)
            return dict(existing)

    def list_devices(self):
        with self.lock:
            return sorted(
                self.devices.values(),
                key=lambda item: (item.get("name", item.get("id", "")), item.get("id", "")),
            )

    def queue_command(self, device_ids, action, **extra):
        command = {"action": action}
        command.update({key: value for key, value in extra.items() if value not in (None, "")})

        with self.lock:
            for device_id in device_ids:
                self.commands[str(device_id)] = dict(command)
            return command

    def poll_command(self, device_id):
        with self.lock:
            return self.commands.pop(str(device_id), None)

    def poll_alert(self, device_id):
        with self.lock:
            queue = self.alerts.setdefault(str(device_id), [])
            if not queue:
                return None
            alert = dict(queue.pop(0))
            alert["queue_remaining"] = len(queue)
            return alert

    def screen_payload(self, screen):
        with self.lock:
            settings = self.store.load_settings()
            self.settings = settings
        with self.dashboard_lock:
            payload = self.dashboard.build(screen, settings)
        return payload

    def refresh_dashboard(self):
        with self.lock:
            settings = self.store.load_settings()
            self.settings = settings
        with self.dashboard_lock:
            _, new_alerts = self.dashboard.refresh_data(settings)
        if not new_alerts:
            return

        deliverable = [
            alert
            for alert in new_alerts
            if alert and (alert.get("show_popup") or alert.get("play_sound"))
        ]
        if not deliverable:
            return

        with self.lock:
            for device_id in self.devices:
                queue = self.alerts.setdefault(str(device_id), [])
                queue.extend(dict(alert) for alert in deliverable)

    def send_test_notification(self, title, message, sound_name="", play_sound=True, device_ids=None):
        with self.lock:
            settings = self.store.load_settings()
            self.settings = settings
            target_ids = [str(device_id) for device_id in (device_ids or self.devices.keys()) if str(device_id)]

        if not target_ids:
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
            return False, "Enter some notification text first."

        with self.lock:
            for device_id in target_ids:
                queue = self.alerts.setdefault(str(device_id), [])
                queue.append(dict(alert))

        return True, f"Queued a test notification for {len(target_ids)} Pi screen(s)."

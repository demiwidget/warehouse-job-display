from datetime import datetime
from threading import RLock

from manager_app.current_rms import DashboardBuilder
from manager_app.settings_store import SettingsStore


class ManagerState:
    def __init__(self, store=None):
        self.store = store or SettingsStore()
        self.lock = RLock()
        self.settings = self.store.load_settings()
        self.devices = self.store.load_devices()
        self.commands = {}
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

        now = datetime.now().isoformat(timespec="seconds")
        with self.lock:
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
            self.store.save_devices(self.devices)
            return dict(existing)

    def list_devices(self):
        with self.lock:
            return sorted(self.devices.values(), key=lambda item: item.get("name", item.get("id", "")))

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

    def screen_payload(self, screen):
        with self.lock:
            settings = self.store.load_settings()
            self.settings = settings
        return self.dashboard.build(screen, settings)

    def refresh_dashboard(self):
        self.dashboard.refresh()

import ipaddress
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import requests

from manager_app.security import TOKEN_HEADER


def remote_config_file():
    appdata = os.environ.get("APPDATA")
    if appdata:
        base = Path(appdata) / "WarehouseDashboardRemote"
    else:
        base = Path.home() / ".warehouse-dashboard-remote"
    return base / "connection.json"


def load_remote_connection():
    path = remote_config_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def save_remote_connection(manager_url, admin_token=""):
    path = remote_config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "manager_url": normalize_manager_url(manager_url),
        "admin_token": str(admin_token or "").strip(),
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def normalize_manager_url(value):
    raw_value = str(value or "").strip().rstrip("/")
    if not raw_value:
        raise ValueError("Remote manager URL is required.")

    if "://" not in raw_value:
        raw_value = f"http://{raw_value}"

    parsed = urlparse(raw_value)
    if not parsed.hostname:
        raise ValueError(f"Could not understand Manager Pi address: {value}")

    try:
        parsed_ip = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        parsed_ip = None
    if parsed_ip and parsed_ip.is_loopback:
        raise ValueError(
            f"{parsed.hostname} is a local loopback address. Use the Manager Pi's network IP, usually 192.168.x.x."
        )

    if parsed.port is None:
        raw_value = raw_value.rstrip("/") + ":8765"

    return raw_value.rstrip("/")


class RemoteManagerState:
    is_remote = True

    def __init__(self, base_url, admin_token=""):
        self.base_url = normalize_manager_url(base_url)
        self.admin_token = str(admin_token or "").strip()

    def install_host(self):
        parsed = urlparse(self.base_url)
        return parsed.hostname or "MANAGER_PI_IP"

    def _url(self, path):
        return self.base_url + path

    def _headers(self, extra=None):
        headers = dict(extra or {})
        if self.admin_token:
            headers[TOKEN_HEADER] = self.admin_token
        return headers

    def _handle_response(self, response):
        if response.status_code == 401:
            raise PermissionError("Manager Pi login failed. Check the PC Login Code shown on the Manager Pi screen.")
        response.raise_for_status()
        return response.json()

    def _get(self, path, **params):
        response = requests.get(self._url(path), params=params, headers=self._headers(), timeout=15)
        return self._handle_response(response)

    def _post(self, path, payload=None, **kwargs):
        headers = kwargs.pop("headers", None)
        response = requests.post(
            self._url(path),
            json=payload or {},
            headers=self._headers(headers),
            timeout=30,
            **kwargs,
        )
        return self._handle_response(response)

    def log_activity(self, *_args, **_kwargs):
        return None

    def log_exception(self, category, message, error=None):
        return self.log_activity(category, f"{message}: {error}" if error else message, level="error")

    def get_settings(self, include_secret=False):
        return self._get("/api/settings", include_secret=1 if include_secret else 0)

    def save_settings(self, updates):
        return self._post("/api/settings", updates)

    def test_current_rms(self, api_settings=None):
        result = self._post("/api/current-rms/test", api_settings or {})
        return bool(result.get("success")), str(result.get("message", ""))

    def refresh_dashboard(self):
        self._post("/api/dashboard/refresh")
        return None

    def list_devices(self):
        return self._get("/api/devices")

    def queue_command(self, device_ids, action, **extra):
        payload = {"device_ids": device_ids, "action": action}
        payload.update({key: value for key, value in extra.items() if value not in (None, "")})
        return self._post("/api/devices/command", payload).get("command", {})

    def remove_devices(self, device_ids):
        return int(self._post("/api/devices/remove", {"device_ids": device_ids}).get("removed", 0) or 0)

    def send_test_notification(self, title, message, sound_name="", play_sound=True, device_ids=None):
        result = self._post(
            "/api/notifications/test",
            {
                "title": title,
                "message": message,
                "sound_name": sound_name,
                "play_sound": play_sound,
                "device_ids": device_ids,
            },
        )
        return bool(result.get("success")), str(result.get("message", ""))

    def list_activity(self, category="All", level="All", limit=500):
        return self._get("/api/activity", category=category, level=level, limit=limit)

    def clear_activity(self):
        self._post("/api/activity/clear")

    def get_update_status(self):
        return self._get("/api/update-status")

    def refresh_update_status(self, force=False):
        if force:
            return self._post("/api/update-status/refresh")
        return self.get_update_status()

    def upload_sound(self, source_path):
        source = Path(source_path)
        with source.open("rb") as handle:
            response = requests.post(
                self._url("/api/sounds/upload"),
                files={"file": (source.name, handle, "audio/wav")},
                headers=self._headers(),
                timeout=60,
            )
        result = self._handle_response(response)
        if not result.get("success"):
            raise RuntimeError(str(result.get("message") or "Sound upload failed."))
        return str(result.get("filename") or source.name)

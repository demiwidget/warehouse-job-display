import json
from copy import deepcopy
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "manager_data"
SETTINGS_FILE = DATA_DIR / "settings.json"
DEVICES_FILE = DATA_DIR / "devices.json"

DEFAULT_SETTINGS = {
    "server": {
        "host": "0.0.0.0",
        "port": 8765,
    },
    "current_rms": {
        "api_base": "https://api.current-rms.com/api/v1",
        "api_key": "",
        "subdomain": "",
        "view_id": "",
        "per_page": 48,
        "max_pages": 2,
        "item_detail_limit": 12,
        "views": {
            "today_out": "1000063",
            "today_in": "1000065",
            "tomorrow_out": "1000064",
            "tomorrow_in": "1000066",
            "prep": "1000067",
            "outstanding": "1000070",
        },
        "excluded_item_ids": [
            "691109",
            "691110",
            "741400",
            "741401",
        ],
        "collection_locations": {
            "1000046": "Harpers Farm",
            "1000047": "Iden Green Farm",
        },
    },
    "alerts": {
        "poll_seconds": 60,
        "startup_sound_suppress_seconds": 20,
        "quiet_hours_start": 21,
        "quiet_hours_end": 7,
        "history_limit": 500,
        "event_types": {
            "new_job_today": {
                "enabled": True,
                "show_popup": True,
                "play_sound": True,
                "sound": "job-today.wav",
            },
            "new_job_tomorrow": {
                "enabled": True,
                "show_popup": True,
                "play_sound": True,
                "sound": "job-tomorrow.wav",
            },
            "new_job_next_7_days": {
                "enabled": True,
                "show_popup": True,
                "play_sound": True,
                "sound": "next-7-days.wav",
            },
            "job_returned": {
                "enabled": True,
                "show_popup": True,
                "play_sound": True,
                "sound": "job-returned.wav",
            },
            "job_changed_today": {
                "enabled": True,
                "show_popup": True,
                "play_sound": True,
                "sound": "job-changes.wav",
            },
            "job_changed_tomorrow": {
                "enabled": True,
                "show_popup": True,
                "play_sound": True,
                "sound": "job-changes.wav",
            },
            "job_changed_next_7_days": {
                "enabled": True,
                "show_popup": True,
                "play_sound": True,
                "sound": "job-changes.wav",
            },
        },
    },
}


def _merge_defaults(defaults, values):
    merged = deepcopy(defaults)
    for key, value in (values or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_defaults(merged[key], value)
        else:
            merged[key] = value
    return merged


class SettingsStore:
    def __init__(self, settings_file=SETTINGS_FILE, devices_file=DEVICES_FILE):
        self.settings_file = Path(settings_file)
        self.devices_file = Path(devices_file)
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)

    def load_settings(self):
        if not self.settings_file.exists():
            self.save_settings(DEFAULT_SETTINGS)
            return deepcopy(DEFAULT_SETTINGS)

        try:
            data = json.loads(self.settings_file.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        return _merge_defaults(DEFAULT_SETTINGS, data)

    def save_settings(self, settings):
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)
        safe_settings = _merge_defaults(DEFAULT_SETTINGS, settings)
        self.settings_file.write_text(json.dumps(safe_settings, indent=2), encoding="utf-8")
        return safe_settings

    def load_devices(self):
        if not self.devices_file.exists():
            return {}

        try:
            data = json.loads(self.devices_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

        if not isinstance(data, dict):
            return {}
        return data

    def save_devices(self, devices):
        self.devices_file.parent.mkdir(parents=True, exist_ok=True)
        self.devices_file.write_text(json.dumps(devices, indent=2), encoding="utf-8")

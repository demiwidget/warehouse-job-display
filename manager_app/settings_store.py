import json
import os
from copy import deepcopy
from pathlib import Path
from tempfile import NamedTemporaryFile

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
        "api_workers": 12,
        "item_detail_limit": 12,
        "views": {
            "today_out": "1000063",
            "today_in": "1000065",
            "tomorrow_out": "1000064",
            "tomorrow_in": "1000066",
            "prep": "1000067",
            "outstanding": "1000070",
        },
        "quarantines": {
            "enabled": True,
            "department_field": "department_responsible_for_repair",
            "per_page": 100,
            "max_pages": 20,
            "active_only": True,
            "excluded_department_ids": [
                "1000067",
            ],
            "department_mappings": {
                "1000055": "Technology",
                "1000056": "TV Lights",
                "1000057": "Rigging",
                "1000058": "Power",
                "1000059": "3rd Party",
                "1000090": "Adam Baker Repairs",
            },
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
        "department_routing": {
            "enabled": True,
            "field_names": [
                "prep_department",
                "prep department",
                "Prep Department",
            ],
            "send_unknown_to_all": True,
            "routes": {
                "Rigging": [
                    "rigging",
                ],
                "Power": [
                    "power",
                ],
                "Technology": [
                    "technology",
                ],
                "TV Lights": [
                    "tv lights",
                ],
                "3rd Party": [
                    "3rd party",
                ],
            },
        },
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

DEPRECATED_QUARANTINE_DEPARTMENT_IDS = {"1000067"}
LEGACY_QUARANTINE_DEPARTMENT_NAMES = {
    "1000055": {"Department 1", "Department 1000055"},
    "1000067": {"Technology", "Department 1000067"},
}


def _merge_defaults(defaults, values):
    merged = deepcopy(defaults)
    for key, value in (values or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_defaults(merged[key], value)
        else:
            merged[key] = value
    return merged


def _migrate_settings(settings):
    quarantine_settings = settings.get("current_rms", {}).get("quarantines", {})
    mappings = quarantine_settings.get("department_mappings", {})
    if not isinstance(mappings, dict):
        mappings = {}
    default_mappings = DEFAULT_SETTINGS["current_rms"]["quarantines"]["department_mappings"]
    excluded_ids = quarantine_settings.get("excluded_department_ids", [])
    if isinstance(excluded_ids, str):
        excluded_ids = [item.strip() for item in excluded_ids.split(",") if item.strip()]
    if not isinstance(excluded_ids, list):
        excluded_ids = []
    excluded_ids = {str(item).strip() for item in excluded_ids if str(item).strip()}
    excluded_ids.update(DEPRECATED_QUARANTINE_DEPARTMENT_IDS)
    quarantine_settings["excluded_department_ids"] = sorted(excluded_ids)
    for department_id in DEPRECATED_QUARANTINE_DEPARTMENT_IDS:
        mappings.pop(department_id, None)
    for department_id, default_name in default_mappings.items():
        current_name = str(mappings.get(department_id, "")).strip()
        old_placeholder = f"Department {department_id}"
        legacy_names = LEGACY_QUARANTINE_DEPARTMENT_NAMES.get(department_id, set())
        if not current_name or current_name == old_placeholder or current_name in legacy_names:
            mappings[department_id] = default_name
    quarantine_settings["department_mappings"] = mappings

    alerts = settings.get("alerts", {})
    routing = alerts.get("department_routing", {})
    if not isinstance(routing, dict):
        routing = {}
    field_names = routing.get("field_names", [])
    if isinstance(field_names, str):
        field_names = [item.strip() for item in field_names.split(",") if item.strip()]
    if not isinstance(field_names, list):
        field_names = []
    routing["field_names"] = [str(item).strip() for item in field_names if str(item).strip()]

    routes = routing.get("routes", {})
    if not isinstance(routes, dict):
        routes = {}
    clean_routes = {}
    for department, targets in routes.items():
        department_name = str(department).strip()
        if not department_name:
            continue
        if isinstance(targets, str):
            targets = [item.strip() for item in targets.split(",") if item.strip()]
        if not isinstance(targets, list):
            targets = []
        clean_targets = [str(item).strip() for item in targets if str(item).strip()]
        if clean_targets:
            clean_routes[department_name] = clean_targets
    routing["routes"] = clean_routes
    routing["enabled"] = bool(routing.get("enabled", True))
    routing["send_unknown_to_all"] = bool(routing.get("send_unknown_to_all", True))
    alerts["department_routing"] = routing
    return settings


def _atomic_write_text(path, text):
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
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temp_name).replace(path)
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except Exception:
                pass


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
        return _migrate_settings(_merge_defaults(DEFAULT_SETTINGS, data))

    def save_settings(self, settings):
        safe_settings = _migrate_settings(_merge_defaults(DEFAULT_SETTINGS, settings))
        _atomic_write_text(self.settings_file, json.dumps(safe_settings, indent=2))
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
        _atomic_write_text(self.devices_file, json.dumps(devices, indent=2))

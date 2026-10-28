from urllib.parse import quote

import requests


def as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def is_night_sleep_maintenance(maintenance):
    maintenance = maintenance if isinstance(maintenance, dict) else {}
    if not as_bool(maintenance.get("enabled", False)):
        return False

    mode = str(maintenance.get("mode") or "").strip().lower()
    if mode:
        return mode == "night_sleep"

    text = str(maintenance.get("text") or "").strip().lower()
    return as_bool(maintenance.get("clear_notifications", False)) or "manager is sleeping" in text


def manager_night_sleep_state(cfg, request_get=None):
    server = str(cfg.get("server") or "").strip().rstrip("/")
    screen = str(cfg.get("screen") or "today").strip() or "today"
    if not server:
        return None

    request_get = request_get or requests.get
    try:
        response = request_get(f"{server}/screen/{quote(screen, safe='')}", timeout=5)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    title = str(payload.get("title") or "").strip().lower()
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    status = str(summary.get("Status") or summary.get("status") or "").strip().lower()
    return title == "manager sleeping" or status == "sleeping"


def reconcile_night_sleep_config(cfg, request_get=None):
    maintenance = cfg.get("maintenance") if isinstance(cfg.get("maintenance"), dict) else {}
    if not is_night_sleep_maintenance(maintenance):
        return False

    if manager_night_sleep_state(cfg, request_get=request_get) is not False:
        return False

    updated = dict(maintenance)
    updated["enabled"] = False
    updated["mode"] = "night_sleep"
    cfg["maintenance"] = updated
    return True

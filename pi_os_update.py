import json
import os
import platform
import shutil
from pathlib import Path


OS_UPDATE_STATUS_FILE = Path("/var/lib/warehouse-dashboard/os-update-status.json")
OS_UPDATE_ACTIVE_STATES = {"checking", "preparing", "updating", "finalising"}
OS_UPDATE_TERMINAL_STATES = {"available", "current", "complete", "attention", "failed"}


def as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def safe_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def current_boot_id():
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def os_release_details():
    details = {}
    try:
        for raw_line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if "=" not in raw_line:
                continue
            key, value = raw_line.split("=", 1)
            details[key.strip()] = value.strip().strip('"')
    except OSError:
        pass
    return {
        "os_name": details.get("PRETTY_NAME") or platform.system() or "Unknown",
        "os_version": details.get("VERSION_ID") or "",
        "os_codename": details.get("VERSION_CODENAME") or "",
        "kernel": platform.release(),
    }


def default_os_update_status():
    details = os_release_details()
    try:
        free_bytes = shutil.disk_usage("/").free
    except OSError:
        free_bytes = 0
    return {
        "supported": bool(os.name != "nt" and shutil.which("apt-get") and shutil.which("systemctl")),
        "state": "not_checked",
        "progress": 0,
        "title": "Not checked",
        "detail": "Run an OS update check from the manager.",
        "mode": "",
        "pending_count": 0,
        "packages": [],
        "removal_count": 0,
        "removals": [],
        "free_bytes": int(free_bytes),
        "reboot_required": False,
        "boot_id": current_boot_id(),
        "started_at": "",
        "updated_at": "",
        "finished_at": "",
        "error": "",
        **details,
    }


def read_os_update_status(path=OS_UPDATE_STATUS_FILE):
    status = default_os_update_status()
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        payload = {}
    if isinstance(payload, dict):
        status.update(payload)
    status["supported"] = bool(status.get("supported", True))
    status["progress"] = max(0, min(100, safe_int(status.get("progress"), 0)))
    status["pending_count"] = max(0, safe_int(status.get("pending_count"), 0))
    status["removal_count"] = max(0, safe_int(status.get("removal_count"), 0))
    status["reboot_required"] = as_bool(status.get("reboot_required", False))
    return status


def os_update_is_terminal(status):
    return str((status or {}).get("state") or "").strip().lower() in OS_UPDATE_TERMINAL_STATES


def parse_apt_simulation(output):
    packages = []
    removals = []
    for raw_line in str(output or "").splitlines():
        line = raw_line.strip()
        if line.startswith("Inst "):
            parts = line.split()
            if len(parts) > 1:
                packages.append(parts[1])
        elif line.startswith("Remv "):
            parts = line.split()
            if len(parts) > 1:
                removals.append(parts[1])
    return list(dict.fromkeys(packages)), list(dict.fromkeys(removals))


def reconcile_os_update_maintenance(cfg, status=None):
    maintenance = cfg.get("maintenance", {}) if isinstance(cfg.get("maintenance", {}), dict) else {}
    if not as_bool(maintenance.get("enabled")) or str(maintenance.get("mode") or "") != "os_update":
        return False

    status = status or read_os_update_status()
    state = str(status.get("state") or "").strip().lower()
    should_clear = state in {"available", "current", "attention", "failed"}
    if state == "complete":
        update_boot_id = str(status.get("boot_id") or "").strip()
        should_clear = not update_boot_id or update_boot_id != current_boot_id() or not status.get("reboot_required")
    if state == "not_checked" and current_boot_id():
        should_clear = True

    if not should_clear:
        return False
    maintenance["enabled"] = False
    cfg["maintenance"] = maintenance
    return True

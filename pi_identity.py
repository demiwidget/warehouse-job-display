import re
import socket
import uuid
from pathlib import Path

from app_version import CURRENT_VERSION


PLACEHOLDER_DEVICE_NAMES = {"", "Warehouse Screen 1"}
PLACEHOLDER_DEVICE_IDS = {"", "pi-1"}


def _slugify(value, fallback="pi"):
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return cleaned or fallback


def _mac_address_candidates():
    seen = set()
    net_root = Path("/sys/class/net")
    preferred = []
    if net_root.exists():
        preferred.extend([net_root / "eth0" / "address", net_root / "wlan0" / "address"])
        preferred.extend(sorted(net_root.glob("*/address")))

    for path in preferred:
        interface = path.parent.name
        if interface == "lo" or not path.exists():
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            continue
        normalized = re.sub(r"[^0-9a-fA-F]", "", raw).lower()
        if not normalized or normalized in seen or set(normalized) == {"0"}:
            continue
        seen.add(normalized)
        yield normalized


def hardware_fingerprint():
    for normalized in _mac_address_candidates():
        return normalized[:12]

    for path in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
        if not path.exists():
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            continue
        normalized = re.sub(r"[^0-9a-fA-F]", "", raw).lower()
        if normalized:
            return normalized[:12]

    return f"{uuid.getnode():012x}"[-12:]


def build_device_uid(label=""):
    suffix = hardware_fingerprint()
    prefix = _slugify(label or socket.gethostname() or "pi")
    if suffix and not prefix.endswith(suffix):
        return f"{prefix}-{suffix}"
    return prefix


def ensure_device_identity(cfg):
    changed = False
    hostname = socket.gethostname().strip() or "pi"

    device_name = str(cfg.get("device_name", "")).strip()
    if device_name in PLACEHOLDER_DEVICE_NAMES:
        device_name = hostname
        cfg["device_name"] = device_name
        changed = True

    legacy_device_id = str(cfg.get("device_id", "")).strip()
    device_uid = str(cfg.get("device_uid", "")).strip()
    suffix = hardware_fingerprint()

    if not device_uid:
        normalized_legacy = _slugify(legacy_device_id, "") if legacy_device_id else ""
        if normalized_legacy and suffix and normalized_legacy.endswith(suffix):
            device_uid = normalized_legacy
        else:
            label = legacy_device_id or device_name or hostname
            device_uid = build_device_uid(label)
        cfg["device_uid"] = device_uid
        changed = True

    if legacy_device_id in PLACEHOLDER_DEVICE_IDS:
        cfg["device_id"] = device_uid
        changed = True

    return cfg, changed, legacy_device_id, device_uid


def registration_id(cfg):
    cfg, _changed, _legacy_device_id, device_uid = ensure_device_identity(dict(cfg))
    return device_uid


def registration_payload(cfg, screen=None):
    cfg, changed, legacy_device_id, device_uid = ensure_device_identity(cfg)
    payload = {
        "id": device_uid,
        "name": str(cfg.get("device_name", "")).strip() or device_uid,
        "screen": screen if screen is not None else cfg.get("screen", "today"),
        "version": str(cfg.get("version", "")).strip() or CURRENT_VERSION,
    }
    if legacy_device_id and legacy_device_id != device_uid:
        payload["legacy_id"] = legacy_device_id
    return cfg, changed, payload

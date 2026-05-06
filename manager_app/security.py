import base64
from datetime import datetime
import hashlib
import json
import os
import secrets
from pathlib import Path
from tempfile import NamedTemporaryFile

from manager_app.settings_store import DATA_DIR


SECURITY_FILE = DATA_DIR / "security.json"
INITIAL_PASSWORD_FILE = DATA_DIR / "initial_admin_password.txt"
TOKEN_HEADER = "X-Warehouse-Admin-Token"
PASSWORD_ITERATIONS = 240000
MIN_PASSWORD_LENGTH = 8


def _atomic_write_json(path, data):
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
            json.dump(data, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temp_name).replace(path)
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except Exception:
                pass


def _load_security():
    try:
        data = json.loads(SECURITY_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def _save_security(data):
    _atomic_write_json(SECURITY_FILE, data)
    try:
        SECURITY_FILE.chmod(0o600)
    except Exception:
        pass


def _hash_password(password, salt=None, iterations=PASSWORD_ITERATIONS):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), salt, int(iterations))
    return {
        "algorithm": "pbkdf2_sha256",
        "iterations": int(iterations),
        "salt": base64.b64encode(salt).decode("ascii"),
        "password_hash": base64.b64encode(digest).decode("ascii"),
    }


def _verify_password(data, candidate):
    password_hash = str(data.get("password_hash", "")).strip()
    salt_text = str(data.get("salt", "")).strip()
    if not password_hash or not salt_text:
        return False
    try:
        salt = base64.b64decode(salt_text.encode("ascii"))
        expected = base64.b64decode(password_hash.encode("ascii"))
        iterations = int(data.get("iterations") or PASSWORD_ITERATIONS)
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", str(candidate).encode("utf-8"), salt, iterations)
    return secrets.compare_digest(actual, expected)


def security_status():
    data = _load_security()
    if data.get("password_hash"):
        mode = "password"
    elif str(data.get("admin_token", "")).strip():
        mode = "legacy_code"
    else:
        mode = "unconfigured"
    return {
        "configured": mode != "unconfigured",
        "mode": mode,
        "password_set": mode == "password",
        "legacy_code_active": mode == "legacy_code",
        "updated_at": str(data.get("password_updated_at") or ""),
    }


def ensure_admin_password():
    """Create a hidden first-run password only when no credential exists."""
    data = _load_security()
    if data.get("password_hash"):
        return ""

    legacy_token = str(data.get("admin_token", "")).strip()
    password = legacy_token or secrets.token_urlsafe(12)
    data.update(_hash_password(password))
    data["password_updated_at"] = datetime.now().isoformat(timespec="seconds")
    if legacy_token:
        data["migrated_from_legacy_code"] = True
        data.pop("admin_token", None)
    _save_security(data)
    INITIAL_PASSWORD_FILE.write_text(
        (
            "Warehouse Manager Pi password\n"
            "=============================\n\n"
            f"{password}\n\n"
            "Use this from the PC remote app, then change it in the Manager Pi tab.\n"
        ),
        encoding="utf-8",
    )
    try:
        INITIAL_PASSWORD_FILE.chmod(0o600)
    except Exception:
        pass
    return password


def token_matches(candidate):
    data = _load_security()
    if not data.get("password_hash"):
        ensure_admin_password()
        data = _load_security()

    candidate = str(candidate or "").strip()
    if not candidate:
        return False

    if data.get("password_hash"):
        return _verify_password(data, candidate)

    legacy_token = str(data.get("admin_token", "")).strip()
    return bool(legacy_token) and secrets.compare_digest(candidate, legacy_token)


def set_admin_password(current_password, new_password):
    data = _load_security()
    new_password = str(new_password or "")
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.")

    if data.get("password_hash") or str(data.get("admin_token", "")).strip():
        if not token_matches(current_password):
            raise PermissionError("Current Manager Pi password is incorrect.")

    data = {
        **_hash_password(new_password),
        "password_updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save_security(data)
    try:
        INITIAL_PASSWORD_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    return security_status()


def reset_admin_password(new_password):
    new_password = str(new_password or "")
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.")

    data = {
        **_hash_password(new_password),
        "password_updated_at": datetime.now().isoformat(timespec="seconds"),
        "reset_locally": True,
    }
    _save_security(data)
    try:
        INITIAL_PASSWORD_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    return security_status()

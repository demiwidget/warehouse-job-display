import json
import os
import secrets
from pathlib import Path
from tempfile import NamedTemporaryFile

from manager_app.settings_store import DATA_DIR


SECURITY_FILE = DATA_DIR / "security.json"
TOKEN_HEADER = "X-Warehouse-Admin-Token"


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


def get_admin_token():
    data = _load_security()
    token = str(data.get("admin_token", "")).strip()
    if token:
        return token

    token = secrets.token_hex(8).upper()
    data["admin_token"] = token
    _atomic_write_json(SECURITY_FILE, data)
    return token


def token_matches(candidate):
    token = get_admin_token()
    candidate = str(candidate or "").strip()
    return bool(candidate) and secrets.compare_digest(candidate, token)

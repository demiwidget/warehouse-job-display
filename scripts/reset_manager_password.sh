#!/usr/bin/env bash
set -Eeuo pipefail

log() {
    printf '\n[warehouse-password-reset] %s\n' "$*"
}

fail() {
    printf '\n[warehouse-password-reset] ERROR: %s\n' "$*" >&2
    exit 1
}

APP_DIR="${WAREHOUSE_APP_DIR:-$HOME/warehouse-job-display}"
PASSWORD="${WAREHOUSE_MANAGER_PASSWORD:-}"

if [[ ! -d "$APP_DIR" ]]; then
    fail "Cannot find Warehouse Manager Pi folder: $APP_DIR"
fi

if [[ -z "$PASSWORD" ]]; then
    if [[ ! -t 0 ]]; then
        fail "Run this in an interactive terminal, or set WAREHOUSE_MANAGER_PASSWORD."
    fi
    read -rsp "New Manager Pi password: " PASSWORD
    printf '\n'
    read -rsp "Confirm new Manager Pi password: " CONFIRM_PASSWORD
    printf '\n'
    if [[ "$PASSWORD" != "$CONFIRM_PASSWORD" ]]; then
        fail "Passwords did not match."
    fi
fi

if [[ "${#PASSWORD}" -lt 8 ]]; then
    fail "Password must be at least 8 characters long."
fi

PYTHON_BIN="$APP_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$(command -v python3 2>/dev/null || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
    fail "Python was not found."
fi

APP_USER="${WAREHOUSE_APP_USER:-}"
if [[ -z "$APP_USER" ]]; then
    if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
        APP_USER="$SUDO_USER"
    elif [[ -e "$APP_DIR" ]]; then
        APP_USER="$(stat -c '%U' "$APP_DIR")"
    else
        APP_USER="$(id -un)"
    fi
fi

run_as_app_user() {
    if [[ "$(id -un)" == "$APP_USER" ]]; then
        "$@"
    elif [[ "$(id -u)" -eq 0 ]]; then
        runuser -u "$APP_USER" -- "$@"
    else
        sudo -u "$APP_USER" "$@"
    fi
}

log "Resetting Manager Pi password..."
cd "$APP_DIR"
run_as_app_user env WAREHOUSE_APP_DIR="$APP_DIR" WAREHOUSE_MANAGER_PASSWORD="$PASSWORD" "$PYTHON_BIN" - <<'PY'
import base64
from datetime import datetime
import hashlib
import os
import secrets
from pathlib import Path
from tempfile import NamedTemporaryFile


app_dir = Path(os.environ["WAREHOUSE_APP_DIR"])
password = os.environ["WAREHOUSE_MANAGER_PASSWORD"]
data_dir = app_dir / "manager_data"
security_path = data_dir / "security.json"
initial_password_path = data_dir / "initial_admin_password.txt"
iterations = 240000

salt = secrets.token_bytes(16)
digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
payload = {
    "algorithm": "pbkdf2_sha256",
    "iterations": iterations,
    "salt": base64.b64encode(salt).decode("ascii"),
    "password_hash": base64.b64encode(digest).decode("ascii"),
    "password_updated_at": datetime.now().isoformat(timespec="seconds"),
    "reset_locally": True,
}

data_dir.mkdir(parents=True, exist_ok=True)
temp_name = None
try:
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=data_dir,
        prefix=".security.json.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_name = handle.name
        import json

        json.dump(payload, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    Path(temp_name).replace(security_path)
finally:
    if temp_name:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except Exception:
            pass

security_path.chmod(0o600)
try:
    initial_password_path.unlink(missing_ok=True)
except Exception:
    pass
print("Password reset complete.")
PY

unset PASSWORD
unset WAREHOUSE_MANAGER_PASSWORD

if command -v systemctl >/dev/null 2>&1; then
    log "Restarting Manager Pi services..."
    if [[ "$(id -u)" -eq 0 ]]; then
        systemctl restart warehouse-manager-backend.service || true
        systemctl restart --no-block warehouse-manager-display.service || true
    else
        sudo systemctl restart warehouse-manager-backend.service || true
        sudo systemctl restart --no-block warehouse-manager-display.service || true
    fi
fi

log "Password reset complete. Use the new password in the PC app."

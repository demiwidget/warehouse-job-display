#!/usr/bin/env bash
set -Eeuo pipefail

log() {
    printf '\n[warehouse-manager] %s\n' "$*"
}

fail() {
    printf '\n[warehouse-manager] ERROR: %s\n' "$*" >&2
    exit 1
}

if ! command -v apt-get >/dev/null 2>&1; then
    fail "This installer is intended for Raspberry Pi OS or another Debian-based system."
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$APP_DIR/.venv"
PYTHON_BIN="/usr/bin/python3"
VERSION="$(tr -d '[:space:]' < "$APP_DIR/version.txt" 2>/dev/null || printf '2.0.73')"
SYSTEMCTL_BIN="$(command -v systemctl 2>/dev/null || printf '/usr/bin/systemctl')"
REBOOT_BIN="$(command -v reboot 2>/dev/null || printf '/usr/sbin/reboot')"

if [[ -n "${WAREHOUSE_APP_USER:-}" ]]; then
    APP_USER="$WAREHOUSE_APP_USER"
elif [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
    APP_USER="$SUDO_USER"
else
    APP_USER="$(id -un)"
fi

APP_HOME="$(getent passwd "$APP_USER" | cut -d: -f6)"
APP_UID="$(id -u "$APP_USER")"

if [[ -z "$APP_HOME" || ! -d "$APP_HOME" ]]; then
    fail "Could not determine the home directory for user '$APP_USER'."
fi

if [[ "$(id -u)" -eq 0 ]]; then
    SUDO=()
else
    SUDO=(sudo)
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

log "Installing Warehouse Manager Pi from: $APP_DIR"
log "Services will run as user: $APP_USER"

if [[ "${WAREHOUSE_SKIP_APT:-0}" != "1" ]]; then
    log "Installing system packages..."
    "${SUDO[@]}" apt-get update
    "${SUDO[@]}" apt-get install -y git python3 python3-venv python3-full curl unzip
else
    log "Skipping apt package installation because WAREHOUSE_SKIP_APT=1"
fi

if [[ -d "$APP_DIR/.git" ]]; then
    run_as_app_user git -C "$APP_DIR" config core.fileMode false >/dev/null 2>&1 || true
fi

log "Creating Python virtual environment..."
if [[ ! -d "$VENV_DIR" ]]; then
    run_as_app_user "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

run_as_app_user "$VENV_DIR/bin/python" -m pip install --upgrade pip
run_as_app_user "$VENV_DIR/bin/python" -m pip install -r "$APP_DIR/requirements.txt"
chmod +x "$APP_DIR/scripts/update_manager_pi.sh" "$APP_DIR/scripts/reset_manager_password.sh" 2>/dev/null || true

log "Preparing manager settings..."
run_as_app_user "$PYTHON_BIN" - "$APP_DIR" "$VERSION" <<'PY'
import json
import sys
from pathlib import Path

app_dir = Path(sys.argv[1])
version = sys.argv[2]
data_dir = app_dir / "manager_data"
settings_path = data_dir / "settings.json"
data_dir.mkdir(parents=True, exist_ok=True)

if settings_path.exists():
    data = json.loads(settings_path.read_text(encoding="utf-8"))
else:
    data = {}

server = data.setdefault("server", {})
server["host"] = "0.0.0.0"
server["port"] = int(server.get("port") or 8765)
data["manager_pi"] = {"version": version, "role": "backend"}
settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
PY

log "Preparing manager security..."
security_message="$(
    cd "$APP_DIR"
    run_as_app_user env PYTHONPATH="$APP_DIR" "$VENV_DIR/bin/python" - <<'PY'
from manager_app.security import ensure_admin_password, security_status

password = ensure_admin_password()
status = security_status()
if password:
    print(f"Temporary Manager Pi password: {password}")
    print("Use it from the PC app, then change it in the Manager Pi tab.")
elif status.get("legacy_code_active"):
    print("Temporary legacy password is active. Change it in the PC app.")
else:
    print("Manager Pi password is already configured.")
PY
)"
while IFS= read -r line; do
    [[ -n "$line" ]] && log "$line"
done <<< "$security_message"

log "Writing service environment..."
"${SUDO[@]}" tee /etc/default/warehouse-manager-pi >/dev/null <<ENVFILE
WAREHOUSE_APP_DIR=$APP_DIR
WAREHOUSE_APP_USER=$APP_USER
WAREHOUSE_BACKEND_URL=http://127.0.0.1:8765
ENVFILE

log "Writing limited manager control permissions..."
"${SUDO[@]}" tee /etc/sudoers.d/warehouse-manager-pi >/dev/null <<SUDOERS
# Allow the Warehouse Manager Pi backend to update, restart its own services, and reboot this Pi only.
$APP_USER ALL=(root) NOPASSWD: $SYSTEMCTL_BIN --no-block start warehouse-manager-update.service
$APP_USER ALL=(root) NOPASSWD: $SYSTEMCTL_BIN --no-block restart warehouse-manager-backend.service
$APP_USER ALL=(root) NOPASSWD: $SYSTEMCTL_BIN --no-block restart warehouse-manager-display.service
$APP_USER ALL=(root) NOPASSWD: $REBOOT_BIN
SUDOERS
"${SUDO[@]}" chmod 440 /etc/sudoers.d/warehouse-manager-pi
if command -v visudo >/dev/null 2>&1; then
    "${SUDO[@]}" visudo -cf /etc/sudoers >/dev/null
fi

log "Writing systemd services..."
"${SUDO[@]}" tee /etc/systemd/system/warehouse-manager-backend.service >/dev/null <<SERVICE
[Unit]
Description=Warehouse Manager Pi Backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=/etc/default/warehouse-manager-pi
ExecStart=$VENV_DIR/bin/python -m manager_app.backend
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SERVICE

"${SUDO[@]}" tee /etc/systemd/system/warehouse-manager-display.service >/dev/null <<SERVICE
[Unit]
Description=Warehouse Manager Pi Status Display
After=graphical.target warehouse-manager-backend.service
Wants=warehouse-manager-backend.service

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
Environment=DISPLAY=:0
Environment=HOME=$APP_HOME
Environment=XAUTHORITY=$APP_HOME/.Xauthority
Environment=XDG_RUNTIME_DIR=/run/user/$APP_UID
Environment=PULSE_SERVER=unix:/run/user/$APP_UID/pulse/native
Environment=WAYLAND_DISPLAY=wayland-0
Environment="QT_QPA_PLATFORM=wayland;xcb"
Environment=QT_IM_MODULE=none
Environment=QT_VIRTUALKEYBOARD_DESKTOP_DISABLE=1
ExecStart=$VENV_DIR/bin/python "$APP_DIR/manager_status_display.py"
Restart=always
RestartSec=10

[Install]
WantedBy=graphical.target
SERVICE

"${SUDO[@]}" tee /etc/systemd/system/warehouse-manager-update.service >/dev/null <<SERVICE
[Unit]
Description=Warehouse Manager Pi Manual Update
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$APP_DIR
EnvironmentFile=/etc/default/warehouse-manager-pi
ExecStart=$APP_DIR/scripts/update_manager_pi.sh
TimeoutStartSec=20min

SERVICE

"${SUDO[@]}" tee /etc/systemd/system/warehouse-manager-update-on-boot.service >/dev/null <<SERVICE
[Unit]
Description=Warehouse Manager Pi Update On Boot
After=network-online.target
Wants=network-online.target
Before=warehouse-manager-backend.service warehouse-manager-display.service

[Service]
Type=oneshot
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/env bash -lc 'git -C "$APP_DIR" pull --ff-only origin main && "$VENV_DIR/bin/python" -m pip install -r "$APP_DIR/requirements.txt"'
TimeoutStartSec=20min

[Install]
WantedBy=multi-user.target
SERVICE

log "Enabling and starting Manager Pi services..."
"${SUDO[@]}" systemctl daemon-reload
"${SUDO[@]}" systemctl enable warehouse-manager-backend.service
"${SUDO[@]}" systemctl enable warehouse-manager-display.service
"${SUDO[@]}" systemctl enable warehouse-manager-update-on-boot.service
"${SUDO[@]}" systemctl restart warehouse-manager-backend.service
if ! "${SUDO[@]}" systemctl restart --no-block warehouse-manager-display.service; then
    log "Backend installed, but status display did not start yet. Check desktop autologin if needed."
fi

log "Manager Pi installation complete."
log "Backend logs: sudo journalctl -u warehouse-manager-backend -f"
log "Display logs: sudo journalctl -u warehouse-manager-display -f"

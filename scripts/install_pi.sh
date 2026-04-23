#!/usr/bin/env bash
set -Eeuo pipefail

log() {
    printf '\n[warehouse] %s\n' "$*"
}

fail() {
    printf '\n[warehouse] ERROR: %s\n' "$*" >&2
    exit 1
}

if ! command -v apt-get >/dev/null 2>&1; then
    fail "This installer is intended for Raspberry Pi OS or another Debian-based system."
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="/usr/bin/python3"
VENV_DIR="$APP_DIR/.venv"
SYSTEMCTL_BIN="$(command -v systemctl)"
REBOOT_BIN="$(command -v reboot)"
MANAGER_IP="${WAREHOUSE_MANAGER_IP:-}"
MANAGER_PORT="${WAREHOUSE_MANAGER_PORT:-8765}"
VERSION="$(tr -d '[:space:]' < "$APP_DIR/version.txt" 2>/dev/null || printf '2.0.1')"

if [[ ! -f "$APP_DIR/pi_viewer.py" || ! -f "$APP_DIR/pi_agent.py" ]]; then
    fail "Cannot find pi_viewer.py and pi_agent.py. Run this from the repository scripts directory."
fi

if [[ -z "$SYSTEMCTL_BIN" ]]; then
    fail "Could not find systemctl on this Raspberry Pi."
fi

if [[ -z "$REBOOT_BIN" ]]; then
    fail "Could not find reboot on this Raspberry Pi."
fi

chmod +x "$SCRIPT_DIR/update_pi.sh"

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

log "Installing Warehouse Dashboard from: $APP_DIR"
log "Services will run as user: $APP_USER"

if [[ "${WAREHOUSE_SKIP_APT:-0}" != "1" ]]; then
    log "Updating package lists..."
    "${SUDO[@]}" apt-get update

    log "Installing Python, Git, and desktop runtime packages..."
    "${SUDO[@]}" apt-get install -y git python3 python3-venv python3-full curl unzip
else
    log "Skipping apt package installation because WAREHOUSE_SKIP_APT=1"
fi

log "Creating Python virtual environment..."
if [[ ! -d "$VENV_DIR" ]]; then
    run_as_app_user "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

run_as_app_user "$VENV_DIR/bin/python" -m pip install --upgrade pip
run_as_app_user "$VENV_DIR/bin/python" -m pip install PySide6 requests

if [[ ! -f "$APP_DIR/viewer_config.json" ]]; then
    if [[ -z "$MANAGER_IP" ]]; then
        fail "Set the PC manager address first, for example: WAREHOUSE_MANAGER_IP=192.168.1.90 ./install_pi.sh"
    fi

    HOSTNAME_VALUE="$(hostname)"
    log "Writing initial viewer_config.json..."
    tee "$APP_DIR/viewer_config.json" >/dev/null <<CONFIG
{
  "server": "http://${MANAGER_IP}:${MANAGER_PORT}",
  "device_id": "${HOSTNAME_VALUE}",
  "device_name": "${HOSTNAME_VALUE}",
  "version": "${VERSION}",
  "screen": "today",
  "allow_all_screens": true
}
CONFIG
    "${SUDO[@]}" chown "$APP_USER:$APP_USER" "$APP_DIR/viewer_config.json" || true
else
    log "Keeping existing viewer_config.json."
fi

log "Writing updater environment..."
"${SUDO[@]}" tee /etc/default/warehouse-dashboard >/dev/null <<ENVFILE
WAREHOUSE_APP_DIR=$APP_DIR
WAREHOUSE_APP_USER=$APP_USER
WAREHOUSE_DISPLAY_SERVICE=warehouse-viewer.service
WAREHOUSE_AGENT_SERVICE=warehouse-agent.service
ENVFILE

log "Writing limited restart and reboot permissions for the agent..."
"${SUDO[@]}" tee /etc/sudoers.d/warehouse-dashboard >/dev/null <<SUDOERS
# Allow the warehouse dashboard agent to restart the viewer and reboot the Pi only.
$APP_USER ALL=(root) NOPASSWD: $SYSTEMCTL_BIN restart warehouse-viewer.service
$APP_USER ALL=(root) NOPASSWD: $REBOOT_BIN
SUDOERS
"${SUDO[@]}" chmod 440 /etc/sudoers.d/warehouse-dashboard
if command -v visudo >/dev/null 2>&1; then
    "${SUDO[@]}" visudo -cf /etc/sudoers >/dev/null
fi

log "Writing systemd services..."
if [[ -f /etc/systemd/system/warehouse-refresh.service ]]; then
    log "Removing legacy warehouse-refresh.service..."
    "${SUDO[@]}" systemctl disable --now warehouse-refresh.service >/dev/null 2>&1 || true
    "${SUDO[@]}" rm -f /etc/systemd/system/warehouse-refresh.service
fi

"${SUDO[@]}" tee /etc/systemd/system/warehouse-viewer.service >/dev/null <<SERVICE
[Unit]
Description=Warehouse Dashboard Viewer
After=graphical.target network-online.target warehouse-update-on-boot.service
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
Environment=DISPLAY=:0
Environment=XAUTHORITY=$APP_HOME/.Xauthority
Environment=XDG_RUNTIME_DIR=/run/user/$APP_UID
Environment=WAYLAND_DISPLAY=wayland-0
Environment="QT_QPA_PLATFORM=wayland;xcb"
ExecStart=$VENV_DIR/bin/python "$APP_DIR/pi_viewer.py"
Restart=always
RestartSec=10

[Install]
WantedBy=graphical.target
SERVICE

"${SUDO[@]}" tee /etc/systemd/system/warehouse-agent.service >/dev/null <<SERVICE
[Unit]
Description=Warehouse Dashboard Agent
After=network-online.target warehouse-update-on-boot.service
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=/etc/default/warehouse-dashboard
ExecStart=$VENV_DIR/bin/python "$APP_DIR/pi_agent.py"
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SERVICE

"${SUDO[@]}" tee /etc/systemd/system/warehouse-update.service >/dev/null <<SERVICE
[Unit]
Description=Warehouse Dashboard Auto Update
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
EnvironmentFile=/etc/default/warehouse-dashboard
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/env bash "$APP_DIR/scripts/update_pi.sh" --scheduled
SERVICE

"${SUDO[@]}" tee /etc/systemd/system/warehouse-update-on-boot.service >/dev/null <<SERVICE
[Unit]
Description=Warehouse Dashboard Update On Boot
After=network-online.target
Wants=network-online.target
Before=warehouse-viewer.service warehouse-agent.service

[Service]
Type=oneshot
EnvironmentFile=/etc/default/warehouse-dashboard
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/env bash "$APP_DIR/scripts/update_pi.sh" --scheduled

[Install]
WantedBy=multi-user.target
SERVICE

"${SUDO[@]}" tee /etc/systemd/system/warehouse-update.timer >/dev/null <<SERVICE
[Unit]
Description=Run Warehouse Dashboard Auto Update Regularly

[Timer]
OnBootSec=10min
OnUnitActiveSec=6h
RandomizedDelaySec=15min
Persistent=true
Unit=warehouse-update.service

[Install]
WantedBy=timers.target
SERVICE

log "Enabling and starting services..."
"${SUDO[@]}" systemctl daemon-reload
"${SUDO[@]}" systemctl enable warehouse-viewer.service
"${SUDO[@]}" systemctl enable warehouse-agent.service
"${SUDO[@]}" systemctl enable warehouse-update-on-boot.service
"${SUDO[@]}" systemctl enable warehouse-update.timer
"${SUDO[@]}" systemctl start warehouse-update.timer
"${SUDO[@]}" systemctl restart warehouse-agent.service

if ! "${SUDO[@]}" systemctl restart warehouse-viewer.service; then
    log "The agent was installed, but the fullscreen viewer did not start yet."
    log "This usually means the Raspberry Pi desktop session is not running or auto-login is disabled."
fi

log "Installation complete."
log "Check logs with: sudo journalctl -u warehouse-viewer -u warehouse-agent -f"
log "Manual update: $APP_DIR/scripts/update_pi.sh --restart-display"

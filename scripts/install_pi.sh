#!/usr/bin/env bash
set -Eeuo pipefail

log() {
    printf '\n[warehouse] %s\n' "$*"
}

fail() {
    printf '\n[warehouse] ERROR: %s\n' "$*" >&2
    exit 1
}

update_status() {
    local progress="$1"
    local title="$2"
    local detail="${3:-}"

    if [[ -z "${WAREHOUSE_UPDATE_STATUS_FILE:-}" ]]; then
        return 0
    fi

    /usr/bin/python3 - "$WAREHOUSE_UPDATE_STATUS_FILE" "$progress" "$title" "$detail" <<'PY'
import json
import sys
from pathlib import Path

status_path = Path(sys.argv[1])
payload = {
    "progress": int(float(sys.argv[2] or 0)),
    "state": "running",
    "title": sys.argv[3],
    "detail": sys.argv[4],
}
status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
PY
    chmod 644 "$WAREHOUSE_UPDATE_STATUS_FILE" >/dev/null 2>&1 || true
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
DISABLE_LEGACY_KIOSK="${WAREHOUSE_DISABLE_LEGACY_KIOSK:-1}"
DISABLE_LEGACY_STACK="${WAREHOUSE_DISABLE_LEGACY_STACK:-1}"
SKIP_SERVICE_RESTART="${WAREHOUSE_SKIP_SERVICE_RESTART:-0}"
VERSION="$(tr -d '[:space:]' < "$APP_DIR/version.txt" 2>/dev/null || printf '2.0.26')"

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

disable_service_if_present() {
    local service_name="$1"
    if "${SUDO[@]}" systemctl list-unit-files "$service_name" >/dev/null 2>&1; then
        log "Disabling legacy service: $service_name"
        "${SUDO[@]}" systemctl disable --now "$service_name" >/dev/null 2>&1 || true
    fi

    for service_path in \
        "/etc/systemd/system/$service_name" \
        "/etc/systemd/system/multi-user.target.wants/$service_name" \
        "/etc/systemd/system/graphical.target.wants/$service_name"
    do
        if [[ -e "$service_path" || -L "$service_path" ]]; then
            log "Removing legacy service file: $service_path"
            "${SUDO[@]}" rm -f "$service_path" >/dev/null 2>&1 || true
        fi
    done
}

sanitize_autostart_file() {
    local autostart_file="$1"
    local backup_file=""
    local runner=()

    if [[ ! -f "$autostart_file" ]]; then
        return 0
    fi

    if [[ "$autostart_file" != "$APP_HOME"* && "$(id -u)" -ne 0 ]]; then
        runner=(sudo)
    fi

    backup_file="${autostart_file}.warehouse-backup-$(date +%Y%m%d%H%M%S)"
    "${runner[@]}" cp "$autostart_file" "$backup_file"

    "${runner[@]}" python3 - "$autostart_file" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
pattern = re.compile(r"(chromium|google-chrome|firefox|midori|kiosk|dashboard|node-red|homeassistant|warehouse_pi|warehouse_env|pi_viewer\.py)", re.I)
kept = []
changed = False
for line in lines:
    if pattern.search(line):
        changed = True
        continue
    kept.append(line)

if changed:
    path.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
PY

    log "Backed up legacy autostart file to: $backup_file"
}

sanitize_autostart_directory() {
    local autostart_dir="$1"
    local desktop_file=""
    local runner=()

    if [[ ! -d "$autostart_dir" ]]; then
        return 0
    fi

    if [[ "$autostart_dir" != "$APP_HOME"* && "$(id -u)" -ne 0 ]]; then
        runner=(sudo)
    fi

    for desktop_file in "$autostart_dir"/*.desktop; do
        if [[ ! -f "$desktop_file" ]]; then
            continue
        fi

        if python3 - "$desktop_file" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="ignore")
pattern = re.compile(r"(chromium|google-chrome|firefox|midori|kiosk|dashboard|node-red|homeassistant|home-assistant|8123|1880|warehouse_pi|warehouse_env|pi_viewer\.py)", re.I)
raise SystemExit(0 if pattern.search(text) else 1)
PY
        then
            local backup_file="${desktop_file}.warehouse-disabled-$(date +%Y%m%d%H%M%S)"
            "${runner[@]}" mv "$desktop_file" "$backup_file"
            log "Disabled legacy autostart desktop file: $desktop_file"
        fi
    done
}

disable_matching_service_files() {
    local service_root="$1"
    local runner_type="$2"
    local service_file=""
    local service_name=""

    if [[ ! -d "$service_root" ]]; then
        return 0
    fi

    while IFS= read -r -d '' service_file; do
        if ! python3 - "$service_file" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="ignore")
pattern = re.compile(r"(warehouse_pi|warehouse_env)", re.I)
raise SystemExit(0 if pattern.search(text) else 1)
PY
        then
            continue
        fi

        service_name="$(basename "$service_file")"
        log "Disabling legacy service file by content match: $service_file"
        if [[ "$runner_type" == "system" ]]; then
            "${SUDO[@]}" systemctl disable --now "$service_name" >/dev/null 2>&1 || true
            "${SUDO[@]}" rm -f "$service_file" >/dev/null 2>&1 || true
            "${SUDO[@]}" rm -f "/etc/systemd/system/multi-user.target.wants/$service_name" >/dev/null 2>&1 || true
            "${SUDO[@]}" rm -f "/etc/systemd/system/graphical.target.wants/$service_name" >/dev/null 2>&1 || true
        else
            if [[ -n "${APP_UID:-}" && -S "/run/user/$APP_UID/bus" ]]; then
                run_as_app_user env XDG_RUNTIME_DIR="/run/user/$APP_UID" systemctl --user disable --now "$service_name" >/dev/null 2>&1 || true
            fi
            run_as_app_user rm -f "$service_file" >/dev/null 2>&1 || true
            run_as_app_user rm -f "$APP_HOME/.config/systemd/user/default.target.wants/$service_name" >/dev/null 2>&1 || true
            run_as_app_user rm -f "$APP_HOME/.config/systemd/user/graphical-session.target.wants/$service_name" >/dev/null 2>&1 || true
            run_as_app_user rm -f "$APP_HOME/.config/systemd/user/graphical-session-pre.target.wants/$service_name" >/dev/null 2>&1 || true
        fi
    done < <(find "$service_root" -maxdepth 2 -type f -name "*.service" -print0 2>/dev/null)
}

disable_user_service_if_present() {
    local service_name="$1"
    local user_systemd_dir="$APP_HOME/.config/systemd/user"
    local service_path=""

    if [[ -d "$user_systemd_dir" ]]; then
        for service_path in \
            "$user_systemd_dir/$service_name" \
            "$user_systemd_dir/default.target.wants/$service_name" \
            "$user_systemd_dir/graphical-session.target.wants/$service_name" \
            "$user_systemd_dir/graphical-session-pre.target.wants/$service_name"
        do
            if [[ -e "$service_path" || -L "$service_path" ]]; then
                log "Removing legacy user service file: $service_path"
                run_as_app_user rm -f "$service_path" >/dev/null 2>&1 || true
            fi
        done
    fi

    if [[ -n "${APP_UID:-}" && -S "/run/user/$APP_UID/bus" ]]; then
        run_as_app_user env XDG_RUNTIME_DIR="/run/user/$APP_UID" systemctl --user disable --now "$service_name" >/dev/null 2>&1 || true
    fi
}

kill_legacy_processes() {
    run_as_app_user pkill -f "chromium|google-chrome|firefox|midori|matchbox" >/dev/null 2>&1 || true
    run_as_app_user pkill -f "node-red|node_red" >/dev/null 2>&1 || true
    run_as_app_user pkill -f "homeassistant|home-assistant|hass" >/dev/null 2>&1 || true
    run_as_app_user pkill -f "warehouse_pi/pi_viewer.py|warehouse_env/.*/pi_viewer.py|warehouse_env/bin/python.*/warehouse_pi/pi_viewer.py" >/dev/null 2>&1 || true
    "${SUDO[@]}" pkill -f "chromium|google-chrome|firefox|midori|matchbox" >/dev/null 2>&1 || true
    "${SUDO[@]}" pkill -f "node-red|node_red" >/dev/null 2>&1 || true
    "${SUDO[@]}" pkill -f "homeassistant|home-assistant|hass" >/dev/null 2>&1 || true
    "${SUDO[@]}" pkill -f "warehouse_pi/pi_viewer.py|warehouse_env/.*/pi_viewer.py|warehouse_env/bin/python.*/warehouse_pi/pi_viewer.py" >/dev/null 2>&1 || true
}

disable_legacy_kiosk() {
    if [[ "$DISABLE_LEGACY_KIOSK" != "1" ]]; then
        return 0
    fi

    update_status 70 "Disabling old kiosk startup" "Stopping any old browser dashboard startup so the new viewer can take over."
    log "Disabling legacy browser kiosk startup if present..."

    disable_service_if_present kiosk.service
    disable_service_if_present chromium-kiosk.service
    disable_service_if_present browser-kiosk.service
    disable_service_if_present dashboard-kiosk.service
    disable_service_if_present autostart-browser.service
    disable_service_if_present chromium.service
    disable_service_if_present kiosk-browser.service
    disable_service_if_present dashboard-browser.service
    disable_user_service_if_present chromium.service
    disable_user_service_if_present chromium-kiosk.service
    disable_user_service_if_present browser-kiosk.service
    disable_user_service_if_present kiosk.service

    sanitize_autostart_file "$APP_HOME/.config/lxsession/LXDE-pi/autostart"
    sanitize_autostart_file "$APP_HOME/.config/lxsession/LXDE/autostart"
    sanitize_autostart_file "/etc/xdg/lxsession/LXDE-pi/autostart"
    sanitize_autostart_file "/etc/xdg/lxsession/LXDE/autostart"
    sanitize_autostart_file "$APP_HOME/.config/openbox/autostart"
    sanitize_autostart_file "/etc/xdg/openbox/autostart"
    sanitize_autostart_file "$APP_HOME/.config/wayfire.ini"
    sanitize_autostart_file "/etc/xdg/wayfire.ini"
    sanitize_autostart_directory "$APP_HOME/.config/autostart"
    sanitize_autostart_directory "/etc/xdg/autostart"
    disable_matching_service_files "$APP_HOME/.config/systemd/user" "user"
    disable_matching_service_files "/etc/systemd/system" "system"

    kill_legacy_processes
}

disable_legacy_stack() {
    if [[ "$DISABLE_LEGACY_STACK" != "1" ]]; then
        return 0
    fi

    update_status 72 "Disabling old Home Assistant stack" "Stopping local Node-RED and Home Assistant services on this Pi."
    log "Disabling legacy local Node-RED / Home Assistant services if present..."
    disable_service_if_present nodered.service
    disable_service_if_present node-red.service
    disable_service_if_present node-red-dashboard.service
    disable_service_if_present home-assistant.service
    disable_service_if_present home-assistant@homeassistant.service
    disable_service_if_present home-assistant@pi.service
    disable_service_if_present hass.service
    disable_service_if_present hassio-supervisor.service
    disable_service_if_present hassio-apparmor.service
    disable_service_if_present hassio-audio.service
    disable_service_if_present hassio-dns.service
    disable_service_if_present hassio-hostapd.service
    disable_service_if_present hassio-multicast.service
    disable_service_if_present hassio-observer.service
    disable_service_if_present hassio-updater.service
    disable_user_service_if_present nodered.service
    disable_user_service_if_present node-red.service
    disable_user_service_if_present home-assistant.service
    disable_user_service_if_present hass.service
    kill_legacy_processes
}

log "Installing Warehouse Dashboard from: $APP_DIR"
log "Services will run as user: $APP_USER"

disable_legacy_kiosk
disable_legacy_stack

if [[ "${WAREHOUSE_SKIP_APT:-0}" != "1" ]]; then
    update_status 60 "Updating Raspberry Pi packages" "Refreshing apt package lists."
    log "Updating package lists..."
    "${SUDO[@]}" apt-get update

    update_status 68 "Installing system packages" "Installing Git, Python, and desktop runtime packages."
    log "Installing Python, Git, and desktop runtime packages..."
    "${SUDO[@]}" apt-get install -y git python3 python3-venv python3-full curl unzip alsa-utils
else
    log "Skipping apt package installation because WAREHOUSE_SKIP_APT=1"
fi

update_status 74 "Preparing Python environment" "Checking the local virtual environment."
log "Creating Python virtual environment..."
if [[ ! -d "$VENV_DIR" ]]; then
    run_as_app_user "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

update_status 80 "Installing Python packages" "Installing the dashboard viewer dependencies."
run_as_app_user "$VENV_DIR/bin/python" -m pip install --upgrade pip
run_as_app_user "$VENV_DIR/bin/python" -m pip install PySide6 requests

if [[ ! -f "$APP_DIR/viewer_config.json" ]]; then
    if [[ -z "$MANAGER_IP" ]]; then
        fail "Set the PC manager address first, for example: WAREHOUSE_MANAGER_IP=192.168.1.90 ./install_pi.sh"
    fi

    HOSTNAME_VALUE="$(hostname)"
    DEVICE_ID_VALUE="$(WAREHOUSE_APP_DIR="$APP_DIR" WAREHOUSE_DEVICE_LABEL="$HOSTNAME_VALUE" "$PYTHON_BIN" - <<'PY'
import os
import sys

sys.path.insert(0, os.environ["WAREHOUSE_APP_DIR"])
from pi_identity import build_device_uid

print(build_device_uid(os.environ.get("WAREHOUSE_DEVICE_LABEL", "")))
PY
)"
    update_status 84 "Writing device configuration" "Creating the initial viewer settings for this Pi."
    log "Writing initial viewer_config.json..."
    tee "$APP_DIR/viewer_config.json" >/dev/null <<CONFIG
{
  "server": "http://${MANAGER_IP}:${MANAGER_PORT}",
  "device_id": "${DEVICE_ID_VALUE}",
  "device_name": "${HOSTNAME_VALUE}",
  "device_uid": "${DEVICE_ID_VALUE}",
  "version": "${VERSION}",
  "screen": "today",
  "allow_all_screens": true,
  "audio_output": "hdmi",
  "audio_volume": 100
}
CONFIG
    "${SUDO[@]}" chown "$APP_USER:$APP_USER" "$APP_DIR/viewer_config.json" || true
else
    log "Keeping existing viewer_config.json."
fi

update_status 86 "Syncing device version" "Applying the current dashboard version to this Pi configuration."
run_as_app_user env \
    WAREHOUSE_CONFIG_PATH="$APP_DIR/viewer_config.json" \
    WAREHOUSE_VERSION="$VERSION" \
    WAREHOUSE_MANAGER_IP="$MANAGER_IP" \
    WAREHOUSE_MANAGER_PORT="$MANAGER_PORT" \
    "$PYTHON_BIN" - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["WAREHOUSE_CONFIG_PATH"])
cfg = json.loads(path.read_text(encoding="utf-8"))
changed = False

version = str(os.environ.get("WAREHOUSE_VERSION", "")).strip()
if version and str(cfg.get("version", "")).strip() != version:
    cfg["version"] = version
    changed = True

manager_ip = str(os.environ.get("WAREHOUSE_MANAGER_IP", "")).strip()
manager_port = str(os.environ.get("WAREHOUSE_MANAGER_PORT", "8765")).strip() or "8765"
if manager_ip:
    desired_server = f"http://{manager_ip}:{manager_port}"
    if str(cfg.get("server", "")).strip() != desired_server:
        cfg["server"] = desired_server
        changed = True

audio_output = str(cfg.get("audio_output", "")).strip().lower()
if audio_output not in {"hdmi", "analog", "auto"}:
    cfg["audio_output"] = "hdmi"
    changed = True

try:
    audio_volume = int(float(cfg.get("audio_volume", 100)))
except Exception:
    audio_volume = 100
audio_volume = max(0, min(100, audio_volume))
if cfg.get("audio_volume") != audio_volume:
    cfg["audio_volume"] = audio_volume
    changed = True

if changed:
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
PY

update_status 88 "Writing updater environment" "Saving the dashboard service environment."
log "Writing updater environment..."
"${SUDO[@]}" tee /etc/default/warehouse-dashboard >/dev/null <<ENVFILE
WAREHOUSE_APP_DIR=$APP_DIR
WAREHOUSE_APP_USER=$APP_USER
WAREHOUSE_DISPLAY_SERVICE=warehouse-viewer.service
WAREHOUSE_AGENT_SERVICE=warehouse-agent.service
ENVFILE

update_status 90 "Updating permissions" "Refreshing agent restart and reboot permissions."
log "Writing limited restart and reboot permissions for the agent..."
"${SUDO[@]}" tee /etc/sudoers.d/warehouse-dashboard >/dev/null <<SUDOERS
# Allow the warehouse dashboard agent to restart the viewer, start updates, and reboot the Pi only.
$APP_USER ALL=(root) NOPASSWD: $SYSTEMCTL_BIN restart warehouse-viewer.service
$APP_USER ALL=(root) NOPASSWD: $SYSTEMCTL_BIN start warehouse-update.service
$APP_USER ALL=(root) NOPASSWD: $SYSTEMCTL_BIN --no-block start warehouse-update.service
$APP_USER ALL=(root) NOPASSWD: $REBOOT_BIN
SUDOERS
"${SUDO[@]}" chmod 440 /etc/sudoers.d/warehouse-dashboard
if command -v visudo >/dev/null 2>&1; then
    "${SUDO[@]}" visudo -cf /etc/sudoers >/dev/null
fi

update_status 93 "Updating services" "Writing the latest system services."
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
Environment=HOME=$APP_HOME
Environment=XAUTHORITY=$APP_HOME/.Xauthority
Environment=XDG_RUNTIME_DIR=/run/user/$APP_UID
Environment=PULSE_SERVER=unix:/run/user/$APP_UID/pulse/native
Environment=WAYLAND_DISPLAY=wayland-0
Environment="QT_QPA_PLATFORM=wayland;xcb"
Environment=QT_IM_MODULE=none
Environment=QT_VIRTUALKEYBOARD_DESKTOP_DISABLE=1
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
After=network-online.target graphical.target
Wants=network-online.target graphical.target

[Service]
Type=oneshot
EnvironmentFile=/etc/default/warehouse-dashboard
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/env bash "$APP_DIR/scripts/update_pi.sh" --scheduled
TimeoutStartSec=30min
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
TimeoutStartSec=30min

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

update_status 97 "Restarting services" "Reloading system services and restarting the dashboard."
log "Enabling and starting services..."
"${SUDO[@]}" systemctl daemon-reload
"${SUDO[@]}" systemctl enable warehouse-viewer.service
"${SUDO[@]}" systemctl enable warehouse-agent.service
"${SUDO[@]}" systemctl enable warehouse-update-on-boot.service
"${SUDO[@]}" systemctl enable warehouse-update.timer
"${SUDO[@]}" systemctl start warehouse-update.timer
if [[ "$SKIP_SERVICE_RESTART" == "1" ]]; then
    log "Skipping immediate viewer and agent restart; the updater will relaunch them after the update screen closes."
else
    run_as_app_user pkill -f "$APP_DIR/pi_viewer.py" >/dev/null 2>&1 || true
    "${SUDO[@]}" systemctl restart --no-block warehouse-agent.service

    if ! "${SUDO[@]}" systemctl restart --no-block warehouse-viewer.service; then
        log "The agent was installed, but the fullscreen viewer did not start yet."
        log "This usually means the Raspberry Pi desktop session is not running or auto-login is disabled."
    fi
fi

update_status 99 "Finalising update" "The dashboard is almost ready."
log "Installation complete."
log "Check logs with: sudo journalctl -u warehouse-viewer -u warehouse-agent -f"
log "Manual update: $APP_DIR/scripts/update_pi.sh --restart-display"

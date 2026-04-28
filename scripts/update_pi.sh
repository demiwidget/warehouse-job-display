#!/usr/bin/env bash
set -Eeuo pipefail

log() {
    printf '\n[warehouse-update] %s\n' "$*"
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
APP_USER="${WAREHOUSE_APP_USER:-}"
LOCK_FILE="/tmp/warehouse-dashboard-update.lock"
STATUS_FILE="/tmp/warehouse-dashboard-update-status.json"
VIEWER_SERVICE="${WAREHOUSE_DISPLAY_SERVICE:-warehouse-viewer.service}"
AGENT_SERVICE="${WAREHOUSE_AGENT_SERVICE:-warehouse-agent.service}"
SYSTEMCTL_BIN="${WAREHOUSE_SYSTEMCTL:-$(command -v systemctl 2>/dev/null || true)}"
UPDATE_WINDOW_SCRIPT="$APP_DIR/pi_update_window.py"
UPDATE_WINDOW_STARTED=0
SCHEDULED_MODE=0
RESTART_DISPLAY_MODE=0

for arg in "$@"; do
    case "$arg" in
        --scheduled)
            SCHEDULED_MODE=1
            ;;
        --restart-display)
            RESTART_DISPLAY_MODE=1
            ;;
    esac
done

write_status() {
    local progress="$1"
    local state="$2"
    local title="$3"
    local detail="${4:-}"

    /usr/bin/python3 - "$STATUS_FILE" "$progress" "$state" "$title" "$detail" <<'PY'
import json
import sys
from pathlib import Path

status_path = Path(sys.argv[1])
payload = {
    "progress": int(float(sys.argv[2] or 0)),
    "state": sys.argv[3],
    "title": sys.argv[4],
    "detail": sys.argv[5],
}
status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
PY
    chmod 644 "$STATUS_FILE" >/dev/null 2>&1 || true
}

start_update_window() {
    local python_bin="$APP_DIR/.venv/bin/python"
    local app_home=""
    local app_uid=""
    local _attempt=0

    if [[ "$UPDATE_WINDOW_STARTED" -eq 1 ]]; then
        return 0
    fi

    if [[ ! -x "$python_bin" || ! -f "$UPDATE_WINDOW_SCRIPT" ]]; then
        return 0
    fi

    app_home="$(getent passwd "$APP_USER" | cut -d: -f6)"
    app_uid="$(id -u "$APP_USER" 2>/dev/null || true)"
    if [[ -z "$app_home" || -z "$app_uid" ]]; then
        return 0
    fi

    for _attempt in $(seq 1 30); do
        if [[ -f "$app_home/.Xauthority" || -S "/run/user/$app_uid/wayland-0" ]]; then
            break
        fi
        sleep 1
    done

    if [[ "$(id -u)" -eq 0 ]]; then
        runuser -u "$APP_USER" -- \
            env \
            DISPLAY=:0 \
            XAUTHORITY="$app_home/.Xauthority" \
            XDG_RUNTIME_DIR="/run/user/$app_uid" \
            WAYLAND_DISPLAY=wayland-0 \
            QT_QPA_PLATFORM="wayland;xcb" \
            "$python_bin" "$UPDATE_WINDOW_SCRIPT" "$STATUS_FILE" \
            >/tmp/warehouse-dashboard-update-ui.log 2>&1 &
    else
        env \
            DISPLAY=:0 \
            XAUTHORITY="$app_home/.Xauthority" \
            XDG_RUNTIME_DIR="/run/user/$app_uid" \
            WAYLAND_DISPLAY=wayland-0 \
            QT_QPA_PLATFORM="wayland;xcb" \
            "$python_bin" "$UPDATE_WINDOW_SCRIPT" "$STATUS_FILE" \
            >/tmp/warehouse-dashboard-update-ui.log 2>&1 &
    fi

    UPDATE_WINDOW_STARTED=1
}

pause_for_window() {
    local seconds="$1"
    if [[ "$UPDATE_WINDOW_STARTED" -eq 1 ]]; then
        sleep "$seconds"
    fi
}

stop_update_window() {
    rm -f "$STATUS_FILE" >/dev/null 2>&1 || true
    if [[ "$UPDATE_WINDOW_STARTED" -eq 1 ]] && command -v pkill >/dev/null 2>&1; then
        pkill -f "$UPDATE_WINDOW_SCRIPT $STATUS_FILE" >/dev/null 2>&1 || true
        UPDATE_WINDOW_STARTED=0
    fi
}

handle_error() {
    log "Update failed. Keeping the current dashboard version."
    write_status 100 failed "Update failed" "Keeping the current dashboard version."
    pause_for_window 6
    stop_update_window
}

trap handle_error ERR

if [[ -z "$APP_USER" ]]; then
    if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
        APP_USER="$SUDO_USER"
    else
        APP_USER="$(stat -c '%U' "$APP_DIR")"
    fi
fi

run_git() {
    if [[ "$(id -u)" -eq 0 ]]; then
        runuser -u "$APP_USER" -- git -C "$APP_DIR" "$@"
    else
        git -C "$APP_DIR" "$@"
    fi
}

run_installer() {
    if [[ "$(id -u)" -eq 0 ]]; then
        WAREHOUSE_APP_USER="$APP_USER" WAREHOUSE_UPDATE_STATUS_FILE="$STATUS_FILE" WAREHOUSE_SKIP_SERVICE_RESTART=1 "$APP_DIR/scripts/install_pi.sh"
    else
        sudo env WAREHOUSE_APP_USER="$APP_USER" WAREHOUSE_UPDATE_STATUS_FILE="$STATUS_FILE" WAREHOUSE_SKIP_SERVICE_RESTART=1 "$APP_DIR/scripts/install_pi.sh"
    fi
}

runtime_missing() {
    local python_bin="$APP_DIR/.venv/bin/python"
    [[ ! -x "$python_bin" ]] || ! "$python_bin" -c "import PySide6, requests" >/dev/null 2>&1
}

restart_services() {
    if [[ -z "$SYSTEMCTL_BIN" ]]; then
        log "Could not find systemctl; skipping service restart."
        return 0
    fi

    log "Restarting warehouse viewer and agent services..."
    if [[ "$(id -u)" -eq 0 ]]; then
        if ! "$SYSTEMCTL_BIN" restart --no-block "$AGENT_SERVICE"; then
            log "Agent service restart did not complete cleanly."
        fi
        if ! "$SYSTEMCTL_BIN" restart --no-block "$VIEWER_SERVICE"; then
            log "Viewer service restart did not complete cleanly yet."
        fi
    else
        if ! sudo "$SYSTEMCTL_BIN" restart --no-block "$AGENT_SERVICE"; then
            log "Agent service restart did not complete cleanly."
        fi
        if ! sudo "$SYSTEMCTL_BIN" restart --no-block "$VIEWER_SERVICE"; then
            log "Viewer service restart did not complete cleanly yet."
        fi
    fi
}

finish_without_update() {
    local installer_ran=0
    if runtime_missing; then
        write_status 10 running "Repairing dashboard runtime" "Preparing the update window..."
        start_update_window
        write_status 18 running "Repairing dashboard runtime" "Restoring missing Python packages and services."
        log "Detected missing runtime packages; running installer to restore them."
        run_installer
        installer_ran=1
        write_status 100 complete "Repair complete" "Starting the latest dashboard build."
        pause_for_window 3
        stop_update_window
        restart_services
    fi

    if [[ "$RESTART_DISPLAY_MODE" -eq 1 && "$installer_ran" -eq 0 ]]; then
        restart_services
    fi
}

main() {
    if ! command -v git >/dev/null 2>&1; then
        log "Git is not installed; skipping update."
        finish_without_update
        return 0
    fi

    if ! run_git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        log "This install is not a Git clone; skipping update."
        finish_without_update
        return 0
    fi

    if ! run_git rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
        log "No upstream branch is configured; skipping update."
        finish_without_update
        return 0
    fi

    local tracked_changes
    tracked_changes="$(run_git status --porcelain --untracked-files=no)"
    if [[ -n "$tracked_changes" ]]; then
        log "Tracked local changes detected; skipping auto-update to avoid overwriting them."
        finish_without_update
        return 0
    fi

    if ! run_git fetch --quiet origin; then
        log "Could not reach origin; leaving the current version in place."
        finish_without_update
        return 0
    fi

    local behind_count
    behind_count="$(run_git rev-list --count HEAD..@{u})"
    if [[ "$behind_count" == "0" ]]; then
        if [[ "$SCHEDULED_MODE" -eq 0 ]]; then
            log "Already up to date."
        fi
        finish_without_update
        return 0
    fi

    write_status 8 running "Update found" "Preparing the updater window..."
    start_update_window
    write_status 18 running "Downloading update" "Fetching the latest dashboard files from GitHub."
    log "Applying $behind_count update(s) from GitHub..."
    write_status 38 running "Applying update" "Pulling the latest dashboard code onto this Pi."
    run_git pull --ff-only
    write_status 55 running "Installing update" "Refreshing Python packages, services, and local config."
    run_installer
    write_status 100 complete "Update complete" "Starting the latest dashboard build."
    log "Update complete."
    pause_for_window 3
    stop_update_window
    restart_services
}

if [[ ! -e "$LOCK_FILE" ]]; then
    : > "$LOCK_FILE"
    chmod 644 "$LOCK_FILE" || true
fi

exec 9<"$LOCK_FILE"
if ! flock -n 9; then
    if [[ "$SCHEDULED_MODE" -eq 0 ]]; then
        log "Another update process is already running."
    fi
    exit 0
fi

main

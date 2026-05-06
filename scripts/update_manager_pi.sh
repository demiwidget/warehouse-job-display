#!/usr/bin/env bash
set -Eeuo pipefail

log() {
    printf '\n[warehouse-manager-update] %s\n' "$*"
}

fail() {
    printf '\n[warehouse-manager-update] ERROR: %s\n' "$*" >&2
    exit 1
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
APP_USER="${WAREHOUSE_APP_USER:-}"
LOCK_FILE="/tmp/warehouse-manager-update.lock"
STATUS_FILE="/tmp/warehouse-manager-update-status.json"
LOG_FILE="/tmp/warehouse-manager-update.log"

write_status() {
    local progress="$1"
    local state="$2"
    local title="$3"
    local detail="${4:-}"

    /usr/bin/python3 - "$STATUS_FILE" "$progress" "$state" "$title" "$detail" <<'PY'
import json
import sys
from datetime import datetime
from pathlib import Path

status_path = Path(sys.argv[1])
payload = {
    "progress": int(float(sys.argv[2] or 0)),
    "state": sys.argv[3],
    "title": sys.argv[4],
    "detail": sys.argv[5],
    "updated_at": datetime.now().isoformat(timespec="seconds"),
}
status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
PY
    chmod 644 "$STATUS_FILE" >/dev/null 2>&1 || true
}

handle_error() {
    local exit_code="$?"
    write_status 100 failed "Manager Pi update failed" "Check the Manager Pi update log for details."
    log "Update failed with exit code $exit_code."
    exit "$exit_code"
}

trap handle_error ERR

if [[ -z "$APP_USER" ]]; then
    if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
        APP_USER="$SUDO_USER"
    else
        APP_USER="$(stat -c '%U' "$APP_DIR")"
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

run_git() {
    run_as_app_user git -C "$APP_DIR" "$@"
}

main() {
    : > "$LOG_FILE"
    chmod 644 "$LOG_FILE" >/dev/null 2>&1 || true
    exec > >(tee -a "$LOG_FILE") 2>&1
    write_status 2 running "Starting Manager Pi update" "Preparing GitHub update check."

    if ! command -v git >/dev/null 2>&1; then
        fail "Git is not installed."
    fi

    write_status 8 running "Checking Manager Pi repository" "Verifying the Manager Pi Git clone."
    if ! run_git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        fail "Manager Pi folder is not a Git clone."
    fi

    run_git config core.fileMode false >/dev/null 2>&1 || true

    tracked_changes="$(run_git -c core.fileMode=false status --porcelain --untracked-files=no)"
    if [[ -n "$tracked_changes" ]]; then
        log "Tracked local changes:"
        printf '%s\n' "$tracked_changes"
        fail "Tracked local changes detected; skipping update to avoid overwriting work."
    fi

    write_status 18 running "Fetching GitHub updates" "Contacting GitHub for the latest manager version."
    log "Fetching latest Manager Pi code from GitHub..."
    run_git fetch --quiet origin

    write_status 35 running "Comparing versions" "Checking whether this Manager Pi is behind GitHub."
    behind_count="$(run_git rev-list --count HEAD..@{u})"
    if [[ "$behind_count" == "0" ]]; then
        log "Manager Pi is already up to date."
        write_status 100 complete "Manager Pi already up to date" "No GitHub updates were available."
    else
        write_status 52 running "Applying GitHub update" "Pulling $behind_count update(s) from GitHub."
        log "Applying $behind_count update(s) from GitHub..."
        run_git pull --ff-only
        write_status 74 running "Refreshing services" "Reinstalling Manager Pi runtime and services."
    fi

    chmod +x "$APP_DIR/scripts/install_manager_pi.sh" 2>/dev/null || true
    log "Refreshing Manager Pi runtime and services..."
    WAREHOUSE_APP_USER="$APP_USER" WAREHOUSE_SKIP_APT=1 "$APP_DIR/scripts/install_manager_pi.sh"
    log "Manager Pi update complete."
    write_status 100 complete "Manager Pi update complete" "Manager Pi services have been refreshed."
}

if [[ ! -e "$LOCK_FILE" ]]; then
    : > "$LOCK_FILE"
    chmod 644 "$LOCK_FILE" || true
fi

exec 9<"$LOCK_FILE"
if ! flock -n 9; then
    log "Another Manager Pi update is already running."
    exit 0
fi

main

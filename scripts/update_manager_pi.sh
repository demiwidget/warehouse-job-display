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
    if ! command -v git >/dev/null 2>&1; then
        fail "Git is not installed."
    fi

    if ! run_git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        fail "Manager Pi folder is not a Git clone."
    fi

    tracked_changes="$(run_git status --porcelain --untracked-files=no)"
    if [[ -n "$tracked_changes" ]]; then
        fail "Tracked local changes detected; skipping update to avoid overwriting work."
    fi

    log "Fetching latest Manager Pi code from GitHub..."
    run_git fetch --quiet origin

    behind_count="$(run_git rev-list --count HEAD..@{u})"
    if [[ "$behind_count" == "0" ]]; then
        log "Manager Pi is already up to date."
    else
        log "Applying $behind_count update(s) from GitHub..."
        run_git pull --ff-only
    fi

    chmod +x "$APP_DIR/scripts/install_manager_pi.sh" 2>/dev/null || true
    log "Refreshing Manager Pi runtime and services..."
    WAREHOUSE_APP_USER="$APP_USER" WAREHOUSE_SKIP_APT=1 "$APP_DIR/scripts/install_manager_pi.sh"
    log "Manager Pi update complete."
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

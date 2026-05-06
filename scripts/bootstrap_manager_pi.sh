#!/usr/bin/env bash
set -Eeuo pipefail

log() {
    printf '\n[warehouse-manager-bootstrap] %s\n' "$*"
}

REPO_URL="${WAREHOUSE_REPO_URL:-https://github.com/demiwidget/warehouse-job-display.git}"
REPO_BRANCH="${WAREHOUSE_REPO_BRANCH:-main}"
APP_DIR="${WAREHOUSE_APP_DIR:-$HOME/warehouse-job-display}"
REBOOT_AFTER_INSTALL="${WAREHOUSE_REBOOT_AFTER_INSTALL:-0}"

if [[ "$(id -u)" -eq 0 ]]; then
    SUDO=()
else
    SUDO=(sudo)
fi

if ! command -v git >/dev/null 2>&1; then
    log "Installing Git..."
    "${SUDO[@]}" apt-get update
    "${SUDO[@]}" apt-get install -y git curl
fi

if [[ -d "$APP_DIR/.git" ]]; then
    log "Updating existing repository in $APP_DIR..."
    git -C "$APP_DIR" fetch origin "$REPO_BRANCH"
    git -C "$APP_DIR" checkout "$REPO_BRANCH"
    git -C "$APP_DIR" pull --ff-only origin "$REPO_BRANCH"
elif [[ -e "$APP_DIR" ]]; then
    backup_path="${APP_DIR}.backup-$(date +%Y%m%d%H%M%S)"
    log "Moving existing non-Git app directory to $backup_path"
    mv "$APP_DIR" "$backup_path"
    git clone --branch "$REPO_BRANCH" "$REPO_URL" "$APP_DIR"
else
    log "Cloning latest Warehouse Dashboard from GitHub..."
    git clone --branch "$REPO_BRANCH" "$REPO_URL" "$APP_DIR"
fi

chmod +x "$APP_DIR/scripts/install_manager_pi.sh" 2>/dev/null || true
"$APP_DIR/scripts/install_manager_pi.sh"

if [[ "$REBOOT_AFTER_INSTALL" == "1" ]]; then
    log "Rebooting Manager Pi..."
    "${SUDO[@]}" reboot
fi

#!/usr/bin/env bash
set -Eeuo pipefail

log() {
    printf '\n[warehouse-bootstrap] %s\n' "$*"
}

fail() {
    printf '\n[warehouse-bootstrap] ERROR: %s\n' "$*" >&2
    exit 1
}

REPO_URL="${WAREHOUSE_REPO_URL:-https://github.com/demiwidget/warehouse-job-display.git}"
REPO_BRANCH="${WAREHOUSE_REPO_BRANCH:-main}"
APP_DIR="${WAREHOUSE_APP_DIR:-$HOME/warehouse-job-display}"
MANAGER_IP="${WAREHOUSE_MANAGER_IP:-}"
MANAGER_PORT="${WAREHOUSE_MANAGER_PORT:-8765}"
OVERWRITE_OLD_SYSTEM="${WAREHOUSE_OVERWRITE_OLD_SYSTEM:-0}"
REBOOT_AFTER_INSTALL="${WAREHOUSE_REBOOT_AFTER_INSTALL:-0}"
BACKGROUND_INSTALL="${WAREHOUSE_BACKGROUND_INSTALL:-1}"

if [[ -z "$MANAGER_IP" ]]; then
    fail "Set WAREHOUSE_MANAGER_IP before running this bootstrap command."
fi

if [[ "$(id -u)" -eq 0 ]]; then
    SUDO=()
else
    SUDO=(sudo)
fi

if [[ -n "${WAREHOUSE_APP_USER:-}" ]]; then
    APP_USER="$WAREHOUSE_APP_USER"
elif [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
    APP_USER="$SUDO_USER"
else
    APP_USER="$(id -un)"
fi

repair_package_manager() {
    if ! command -v dpkg >/dev/null 2>&1; then
        return 0
    fi

    log "Checking for interrupted Debian package operations..."
    "${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive dpkg --configure -a
    "${SUDO[@]}" env DEBIAN_FRONTEND=noninteractive apt-get -f install -y
}

ensure_git() {
    if command -v git >/dev/null 2>&1; then
        return 0
    fi

    log "Git is missing; installing Git first..."
    if ! command -v apt-get >/dev/null 2>&1; then
        fail "Git is missing and apt-get is not available."
    fi
    repair_package_manager
    "${SUDO[@]}" apt-get update
    "${SUDO[@]}" apt-get install -y git curl
}

safe_remove_app_dir() {
    if [[ -z "$APP_DIR" || "$APP_DIR" == "/" || "$APP_DIR" == "$HOME" ]]; then
        fail "Refusing to remove unsafe app directory: $APP_DIR"
    fi

    case "$APP_DIR" in
        "$HOME"/*) ;;
        *) fail "Refusing to remove app directory outside this user's home: $APP_DIR" ;;
    esac

    rm -rf "$APP_DIR"
}

disable_old_system() {
    log "Stopping old Node-RED/Home Assistant services if present..."
    "${SUDO[@]}" systemctl stop \
        nodered node-red node-red-dashboard \
        home-assistant home-assistant@homeassistant home-assistant@pi \
        hass docker containerd \
        2>/dev/null || true

    "${SUDO[@]}" systemctl disable \
        nodered node-red node-red-dashboard \
        home-assistant home-assistant@homeassistant home-assistant@pi \
        hass \
        2>/dev/null || true
}

sync_repo() {
    ensure_git

    if [[ "$OVERWRITE_OLD_SYSTEM" == "1" ]]; then
        disable_old_system
        safe_remove_app_dir
    fi

    if [[ -d "$APP_DIR/.git" ]]; then
        log "Updating existing repository in $APP_DIR..."
        git -C "$APP_DIR" config core.fileMode false || true
        git -C "$APP_DIR" fetch origin "$REPO_BRANCH"
        git -C "$APP_DIR" checkout "$REPO_BRANCH"
        git -C "$APP_DIR" pull --ff-only origin "$REPO_BRANCH"
        return 0
    fi

    if [[ -e "$APP_DIR" ]]; then
        local backup_path="${APP_DIR}.backup-$(date +%Y%m%d%H%M%S)"
        log "Existing non-Git app directory found; moving it to $backup_path"
        mv "$APP_DIR" "$backup_path"
    fi

    log "Cloning latest Warehouse Dashboard from GitHub..."
    git clone --branch "$REPO_BRANCH" "$REPO_URL" "$APP_DIR"
    git -C "$APP_DIR" config core.fileMode false || true
}

sync_repo

chmod +x "$APP_DIR/scripts/install_pi.sh" "$APP_DIR/scripts/update_pi.sh" 2>/dev/null || true

if [[ "$BACKGROUND_INSTALL" == "1" ]] && command -v systemd-run >/dev/null 2>&1; then
    if "${SUDO[@]}" systemctl is-active --quiet warehouse-dashboard-install.service; then
        log "The Warehouse Dashboard installer is already running in the background."
        log "Follow its progress with: sudo journalctl -fu warehouse-dashboard-install.service"
        exit 0
    fi

    log "Starting the latest Pi installer as a background system job..."
    "${SUDO[@]}" systemd-run \
        --unit=warehouse-dashboard-install \
        --description="Install Warehouse Dashboard" \
        --collect \
        --property=Type=oneshot \
        --setenv=WAREHOUSE_APP_DIR="$APP_DIR" \
        --setenv=WAREHOUSE_APP_USER="$APP_USER" \
        --setenv=WAREHOUSE_MANAGER_IP="$MANAGER_IP" \
        --setenv=WAREHOUSE_MANAGER_PORT="$MANAGER_PORT" \
        --setenv=WAREHOUSE_DISABLE_LEGACY_KIOSK=1 \
        --setenv=WAREHOUSE_DISABLE_LEGACY_STACK=1 \
        --setenv=WAREHOUSE_REBOOT_AFTER_INSTALL="$REBOOT_AFTER_INSTALL" \
        /bin/bash -c 'set -Eeuo pipefail; cd "$WAREHOUSE_APP_DIR/scripts"; ./install_pi.sh; if [[ "$WAREHOUSE_REBOOT_AFTER_INSTALL" == "1" ]]; then reboot; fi'
    log "Installation is continuing independently of this terminal."
    log "Follow its progress with: sudo journalctl -fu warehouse-dashboard-install.service"
    exit 0
fi

log "Running latest Pi installer..."
cd "$APP_DIR/scripts"
WAREHOUSE_APP_USER="$APP_USER" \
WAREHOUSE_MANAGER_IP="$MANAGER_IP" \
WAREHOUSE_MANAGER_PORT="$MANAGER_PORT" \
WAREHOUSE_DISABLE_LEGACY_KIOSK=1 \
WAREHOUSE_DISABLE_LEGACY_STACK=1 \
./install_pi.sh

if [[ "$REBOOT_AFTER_INSTALL" == "1" ]]; then
    log "Rebooting Pi..."
    "${SUDO[@]}" reboot
fi

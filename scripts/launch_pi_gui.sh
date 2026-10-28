#!/usr/bin/env bash
set -Eeuo pipefail

WAIT_SECONDS="${WAREHOUSE_GUI_WAIT_SECONDS:-0}"

if [[ "${1:-}" == "--wait" ]]; then
    WAIT_SECONDS="${2:-0}"
    shift 2
fi

if [[ "${1:-}" == "--" ]]; then
    shift
fi

if [[ "$#" -eq 0 ]]; then
    printf '[warehouse-gui] ERROR: No application command was supplied.\n' >&2
    exit 2
fi

RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
ELAPSED=0

export XDG_RUNTIME_DIR="$RUNTIME_DIR"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$RUNTIME_DIR/bus}"
export DISPLAY="${DISPLAY:-:0}"

while true; do
    WAYLAND_SOCKET=""
    if [[ -d "$RUNTIME_DIR" ]]; then
        for candidate in "$RUNTIME_DIR"/wayland-*; do
            if [[ -S "$candidate" ]]; then
                WAYLAND_SOCKET="$candidate"
                break
            fi
        done
    fi

    if [[ -n "$WAYLAND_SOCKET" ]]; then
        export WAYLAND_DISPLAY="$(basename "$WAYLAND_SOCKET")"
        export QT_QPA_PLATFORM="wayland;xcb"
        printf '[warehouse-gui] Using Wayland display %s.\n' "$WAYLAND_DISPLAY"
        exec "$@"
    fi

    if [[ -S "/tmp/.X11-unix/X${DISPLAY#:}" ]]; then
        unset WAYLAND_DISPLAY
        export QT_QPA_PLATFORM="xcb"
        printf '[warehouse-gui] Using X11 display %s.\n' "$DISPLAY"
        exec "$@"
    fi

    if [[ "$WAIT_SECONDS" =~ ^[0-9]+$ ]] && [[ "$WAIT_SECONDS" -gt 0 ]] && [[ "$ELAPSED" -ge "$WAIT_SECONDS" ]]; then
        printf '[warehouse-gui] No graphical session became available within %s seconds.\n' "$WAIT_SECONDS" >&2
        exit 1
    fi

    if [[ "$ELAPSED" -eq 0 || $((ELAPSED % 30)) -eq 0 ]]; then
        printf '[warehouse-gui] Waiting for the desktop session in %s...\n' "$RUNTIME_DIR"
    fi
    sleep 1
    ELAPSED=$((ELAPSED + 1))
done

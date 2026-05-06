import getpass
import os
import sys

from manager_app.remote_state import (
    RemoteManagerState,
    load_remote_connection,
    normalize_manager_url,
    save_remote_connection,
)


def prompt_value(label, default=""):
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def prompt_token(default=""):
    if default:
        return default
    try:
        return getpass.getpass("Manager Pi PC Login Code: ").strip()
    except Exception:
        return input("Manager Pi PC Login Code: ").strip()


def main():
    saved = load_remote_connection()
    remote_url = str(os.environ.get("WAREHOUSE_MANAGER_URL") or saved.get("manager_url") or "").strip()
    admin_token = str(os.environ.get("WAREHOUSE_MANAGER_TOKEN") or saved.get("admin_token") or "").strip()

    if len(sys.argv) > 1:
        remote_url = sys.argv[1]
    if not remote_url:
        remote_url = prompt_value("Manager Pi IP or URL, for example 192.168.1.50")
    if len(sys.argv) > 2:
        admin_token = sys.argv[2]

    for attempt in range(3):
        try:
            remote_url = normalize_manager_url(remote_url)
            state = RemoteManagerState(remote_url, admin_token)
            state.get_update_status()
            save_remote_connection(remote_url, admin_token)
            break
        except PermissionError as error:
            print(str(error), file=sys.stderr)
            admin_token = prompt_token("")
            if not admin_token:
                return 1
        except Exception as error:
            print(f"Could not connect to the Manager Pi at {remote_url!r}: {error}", file=sys.stderr)
            if attempt >= 1:
                return 1
            remote_url = prompt_value("Manager Pi IP or URL", "")
            if not remote_url:
                return 1
    else:
        return 1

    from manager_app.main import ManagerWindow, ResilientApplication

    app = ResilientApplication(sys.argv, state)
    app.setQuitOnLastWindowClosed(True)
    window = ManagerWindow(state)
    window.setWindowTitle(f"Warehouse Dashboard Remote Control - {remote_url.rstrip('/')}")
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

import sys

from manager_app.remote_state import RemoteManagerState, normalize_manager_url


def main():
    remote_url = ""
    if len(sys.argv) > 1:
        remote_url = sys.argv[1]
    if not remote_url:
        remote_url = input("Manager Pi URL, for example http://192.168.1.50:8765: ").strip()

    try:
        remote_url = normalize_manager_url(remote_url)
        state = RemoteManagerState(remote_url)
        state.get_update_status()
    except Exception as error:
        print(f"Could not connect to the Manager Pi at {remote_url!r}: {error}", file=sys.stderr)
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

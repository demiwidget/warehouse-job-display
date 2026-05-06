import sys

from PySide6.QtWidgets import QMessageBox

from manager_app.main import ManagerWindow, ResilientApplication
from manager_app.remote_state import RemoteManagerState


def main():
    remote_url = ""
    if len(sys.argv) > 1:
        remote_url = sys.argv[1]
    if not remote_url:
        remote_url = input("Manager Pi URL, for example http://192.168.1.50:8765: ").strip()

    state = RemoteManagerState(remote_url)
    app = ResilientApplication(sys.argv, state)
    app.setQuitOnLastWindowClosed(True)

    try:
        state.get_update_status()
    except Exception as error:
        QMessageBox.warning(None, "Remote Manager", f"Could not connect to the Manager Pi:\n{error}")

    window = ManagerWindow(state)
    window.setWindowTitle(f"Warehouse Dashboard Remote Control - {remote_url.rstrip('/')}")
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

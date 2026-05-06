import os
import sys

from manager_app.remote_state import (
    RemoteManagerState,
    load_remote_connection,
    normalize_manager_url,
    save_remote_connection,
)


class StartupLogState:
    def log_exception(self, category, message, error=None):
        details = f": {error}" if error else ""
        print(f"{category}: {message}{details}", file=sys.stderr)


def connect_to_manager(remote_url, admin_token):
    remote_url = normalize_manager_url(remote_url)
    state = RemoteManagerState(remote_url, admin_token)
    state.get_update_status()
    return remote_url, state


def initial_connection_values():
    saved = load_remote_connection()
    remote_url = str(os.environ.get("WAREHOUSE_MANAGER_URL") or saved.get("manager_url") or "").strip()
    admin_token = str(os.environ.get("WAREHOUSE_MANAGER_TOKEN") or saved.get("admin_token") or "").strip()
    if len(sys.argv) > 1:
        remote_url = sys.argv[1]
    if len(sys.argv) > 2:
        admin_token = sys.argv[2]
    return remote_url, admin_token


def import_ui():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QVBoxLayout,
    )
    from manager_app.main import ManagerWindow, ResilientApplication

    return {
        "QApplication": QApplication,
        "QCheckBox": QCheckBox,
        "QDialog": QDialog,
        "QDialogButtonBox": QDialogButtonBox,
        "QFormLayout": QFormLayout,
        "QLabel": QLabel,
        "QLineEdit": QLineEdit,
        "QMessageBox": QMessageBox,
        "QVBoxLayout": QVBoxLayout,
        "Qt": Qt,
        "ManagerWindow": ManagerWindow,
        "ResilientApplication": ResilientApplication,
    }


def build_login_dialog(ui):
    QApplication = ui["QApplication"]
    QCheckBox = ui["QCheckBox"]
    QDialog = ui["QDialog"]
    QDialogButtonBox = ui["QDialogButtonBox"]
    QFormLayout = ui["QFormLayout"]
    QLabel = ui["QLabel"]
    QLineEdit = ui["QLineEdit"]
    QVBoxLayout = ui["QVBoxLayout"]
    Qt = ui["Qt"]

    class RemoteLoginDialog(QDialog):
        def __init__(self, remote_url="", admin_token="", status_text=""):
            super().__init__()
            self.connected_state = None
            self.connected_url = ""
            self.connected_token = ""

            self.setWindowTitle("Warehouse Remote Manager")
            self.setMinimumWidth(500)

            layout = QVBoxLayout(self)
            heading = QLabel("Connect To Manager Pi")
            heading.setStyleSheet("font-size:24px; font-weight:700;")
            layout.addWidget(heading)

            intro = QLabel(
                "Enter the Manager Pi address and the PC Login Code shown on the Manager Pi screen. "
                "After the first successful login, this PC will remember it."
            )
            intro.setWordWrap(True)
            intro.setStyleSheet("color:#4b5563;")
            layout.addWidget(intro)

            form = QFormLayout()
            self.url_input = QLineEdit(remote_url)
            self.url_input.setPlaceholderText("192.168.1.50 or http://192.168.1.50:8765")
            self.token_input = QLineEdit(admin_token)
            self.token_input.setPlaceholderText("PC Login Code")
            self.token_input.setEchoMode(QLineEdit.Password)
            form.addRow("Manager Pi address", self.url_input)
            form.addRow("PC Login Code", self.token_input)
            layout.addLayout(form)

            self.remember_input = QCheckBox("Remember this Manager Pi on this PC")
            self.remember_input.setChecked(True)
            layout.addWidget(self.remember_input)

            self.status_label = QLabel(status_text)
            self.status_label.setWordWrap(True)
            self.status_label.setStyleSheet("color:#b91c1c;")
            layout.addWidget(self.status_label)

            self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
            self.connect_button = self.buttons.addButton("Connect", QDialogButtonBox.AcceptRole)
            self.connect_button.clicked.connect(self.try_connect)
            self.buttons.rejected.connect(self.reject)
            layout.addWidget(self.buttons)

            self.url_input.returnPressed.connect(self.try_connect)
            self.token_input.returnPressed.connect(self.try_connect)
            self.url_input.setFocus(Qt.OtherFocusReason)

        def try_connect(self):
            remote_url = self.url_input.text().strip()
            admin_token = self.token_input.text().strip()
            self.status_label.setText("Connecting...")
            self.connect_button.setEnabled(False)
            QApplication.setOverrideCursor(Qt.WaitCursor)
            QApplication.processEvents()
            try:
                remote_url, state = connect_to_manager(remote_url, admin_token)
            except PermissionError as error:
                self.status_label.setText(str(error))
                self.token_input.clear()
                self.token_input.setFocus(Qt.OtherFocusReason)
            except Exception as error:
                self.status_label.setText(f"Could not connect: {error}")
            else:
                self.connected_state = state
                self.connected_url = remote_url
                self.connected_token = admin_token
                if self.remember_input.isChecked():
                    save_remote_connection(remote_url, admin_token)
                self.accept()
            finally:
                QApplication.restoreOverrideCursor()
                self.connect_button.setEnabled(True)

    return RemoteLoginDialog


def main():
    ui = import_ui()
    QApplication = ui["QApplication"]
    QDialog = ui["QDialog"]
    QMessageBox = ui["QMessageBox"]
    ManagerWindow = ui["ManagerWindow"]
    ResilientApplication = ui["ResilientApplication"]

    app = ResilientApplication(sys.argv, StartupLogState())
    app.setApplicationName("Warehouse Remote Manager")
    app.setOrganizationName("Warehouse Dashboard")
    app.setQuitOnLastWindowClosed(True)

    remote_url, admin_token = initial_connection_values()
    state = None
    status_text = ""
    if remote_url:
        try:
            remote_url, state = connect_to_manager(remote_url, admin_token)
            save_remote_connection(remote_url, admin_token)
        except PermissionError as error:
            status_text = str(error)
            admin_token = ""
        except Exception as error:
            status_text = f"Could not connect to the Manager Pi: {error}"

    if state is None:
        RemoteLoginDialog = build_login_dialog(ui)
        dialog = RemoteLoginDialog(remote_url, admin_token, status_text)
        if dialog.exec() != QDialog.Accepted:
            return 0
        state = dialog.connected_state
        remote_url = dialog.connected_url

    if state is None:
        QMessageBox.critical(None, "Warehouse Remote Manager", "Could not connect to the Manager Pi.")
        return 1

    app.state = state
    window = ManagerWindow(state)
    window.setWindowTitle(f"Warehouse Remote Manager - {remote_url.rstrip('/')}")
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

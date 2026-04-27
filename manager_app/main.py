import socket
import sys

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from manager_app.server import ServerThread
from manager_app.state import ManagerState


def local_addresses():
    addresses = {"127.0.0.1"}
    hostname = socket.gethostname()
    try:
        addresses.add(socket.gethostbyname(hostname))
    except Exception:
        pass

    try:
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            addresses.add(info[4][0])
    except Exception:
        pass

    return sorted(address for address in addresses if address and not address.startswith("169.254."))


class ConnectionTab(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        layout = QVBoxLayout(self)

        settings = self.state.get_settings(include_secret=True)
        server = settings.get("server", {})

        form = QFormLayout()
        self.host_input = QLineEdit(server.get("host", "0.0.0.0"))
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(int(server.get("port", 8765)))
        form.addRow("Listen address", self.host_input)
        form.addRow("Port", self.port_input)
        layout.addLayout(form)

        self.addresses = QTextEdit()
        self.addresses.setReadOnly(True)
        self.addresses.setMinimumHeight(130)
        layout.addWidget(QLabel("Use one of these PC addresses when installing a Pi:"))
        layout.addWidget(self.addresses)

        save_btn = QPushButton("Save Connection Settings")
        save_btn.clicked.connect(self.save)
        layout.addWidget(save_btn)

        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        layout.addStretch(1)
        self.refresh_addresses()

    def refresh_addresses(self):
        settings = self.state.get_settings(include_secret=True)
        port = settings.get("server", {}).get("port", 8765)
        lines = [f"http://{address}:{port}" for address in local_addresses()]
        self.addresses.setPlainText("\n".join(lines))
        self.status.setText("The manager server is running. Connection changes take effect next time the app starts.")

    def save(self):
        self.state.save_settings(
            {
                "server": {
                    "host": self.host_input.text().strip() or "0.0.0.0",
                    "port": self.port_input.value(),
                }
            }
        )
        self.refresh_addresses()
        QMessageBox.information(self, "Saved", "Connection settings saved. Restart the manager app to use a changed port.")


class CurrentRMSTab(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        layout = QVBoxLayout(self)
        form = QFormLayout()

        rms = self.state.get_settings(include_secret=True).get("current_rms", {})
        self.api_base_input = QLineEdit(rms.get("api_base", "https://api.current-rms.com/api/v1"))
        self.subdomain_input = QLineEdit(rms.get("subdomain", ""))
        self.api_key_input = QLineEdit(rms.get("api_key", ""))
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.view_id_input = QLineEdit(str(rms.get("view_id", "") or ""))
        self.per_page_input = QSpinBox()
        self.per_page_input.setRange(1, 500)
        self.per_page_input.setValue(int(rms.get("per_page", 100)))
        self.max_pages_input = QSpinBox()
        self.max_pages_input.setRange(1, 20)
        self.max_pages_input.setValue(int(rms.get("max_pages", 2)))

        form.addRow("API base URL", self.api_base_input)
        form.addRow("Subdomain", self.subdomain_input)
        form.addRow("API key", self.api_key_input)
        form.addRow("Opportunity view ID", self.view_id_input)
        form.addRow("Rows per page", self.per_page_input)
        form.addRow("Max pages", self.max_pages_input)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        save_btn = QPushButton("Save API Details Locally")
        test_btn = QPushButton("Test Current RMS Connection")
        save_btn.clicked.connect(self.save)
        test_btn.clicked.connect(self.test)
        buttons.addWidget(save_btn)
        buttons.addWidget(test_btn)
        layout.addLayout(buttons)

        note = QLabel(
            "API details are stored only in manager_data/settings.json on this PC. "
            "That folder is ignored by Git and must not be committed."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

    def settings_payload(self):
        return {
            "api_base": self.api_base_input.text().strip() or "https://api.current-rms.com/api/v1",
            "subdomain": self.subdomain_input.text().strip(),
            "api_key": self.api_key_input.text().strip(),
            "view_id": self.view_id_input.text().strip(),
            "per_page": self.per_page_input.value(),
            "max_pages": self.max_pages_input.value(),
        }

    def save(self):
        self.state.save_settings({"current_rms": self.settings_payload()})
        QMessageBox.information(self, "Saved", "Current RMS details saved locally on this PC.")

    def test(self):
        success, message = self.state.test_current_rms(self.settings_payload())
        if success:
            QMessageBox.information(self, "Current RMS Test", message)
        else:
            QMessageBox.warning(self, "Current RMS Test Failed", message)


class PiScreensTab(QWidget):
    COLUMNS = ["ID", "Name", "IP", "Screen", "Version", "Last Seen"]

    def __init__(self, state):
        super().__init__()
        self.state = state
        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.MultiSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

        screen_buttons = QHBoxLayout()
        for label, screen in (
            ("Show Today", "today"),
            ("Show Tomorrow", "tomorrow"),
            ("Show Prep", "prep"),
            ("Show Outstanding", "outstanding"),
            ("Show Notifications", "notifications"),
        ):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _checked=False, target=screen: self.send_screen(target))
            screen_buttons.addWidget(btn)
        layout.addLayout(screen_buttons)

        command_buttons = QHBoxLayout()
        restart_btn = QPushButton("Restart Display App")
        reboot_btn = QPushButton("Reboot Pi")
        refresh_btn = QPushButton("Refresh List")
        restart_btn.clicked.connect(lambda: self.send_action("restart"))
        reboot_btn.clicked.connect(lambda: self.send_action("reboot"))
        refresh_btn.clicked.connect(self.refresh)
        command_buttons.addWidget(restart_btn)
        command_buttons.addWidget(reboot_btn)
        command_buttons.addStretch(1)
        command_buttons.addWidget(refresh_btn)
        layout.addLayout(command_buttons)

        self.status = QLabel("Waiting for Pi screens to register...")
        layout.addWidget(self.status)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(3000)
        self.refresh()

    def selected_device_ids(self):
        rows = {index.row() for index in self.table.selectedIndexes()}
        ids = []
        for row in sorted(rows):
            item = self.table.item(row, 0)
            if item:
                ids.append(item.text())
        return ids

    def refresh(self):
        devices = self.state.list_devices()
        self.table.setRowCount(len(devices))
        for row, device in enumerate(devices):
            values = [
                device.get("id", ""),
                device.get("name", ""),
                device.get("ip", ""),
                device.get("screen", ""),
                device.get("version", ""),
                device.get("last_seen", ""),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self.status.setText(f"{len(devices)} Pi screen(s) registered.")

    def send_screen(self, screen):
        self.send_action("set_screen", screen=screen)

    def send_action(self, action, screen=None):
        device_ids = self.selected_device_ids()
        if not device_ids:
            QMessageBox.warning(self, "No Pi Selected", "Select one or more Pi screens first.")
            return

        self.state.queue_command(device_ids, action, screen=screen)
        self.status.setText(f"Queued {action} for {len(device_ids)} Pi screen(s).")


class ManagerWindow(QMainWindow):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.setWindowTitle("Warehouse Dashboard Manager")
        self.resize(980, 680)

        tabs = QTabWidget()
        tabs.addTab(ConnectionTab(state), "Connection")
        tabs.addTab(CurrentRMSTab(state), "Current RMS")
        tabs.addTab(PiScreensTab(state), "Pi Screens")
        self.setCentralWidget(tabs)


def main():
    state = ManagerState()
    server = ServerThread(state)
    server.start()

    app = QApplication(sys.argv)
    window = ManagerWindow(state)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

import socket
import sys
from threading import Event, Thread

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from manager_app.server import ServerThread
from manager_app.state import ManagerState


ALERT_LABELS = [
    ("new_job_today", "New Job Today"),
    ("new_job_tomorrow", "New Job Tomorrow"),
    ("new_job_next_7_days", "New Job Next 7 Days"),
    ("job_returned", "Job Returned"),
    ("job_changed_today", "Job Changed Today"),
    ("job_changed_tomorrow", "Job Changed Tomorrow"),
    ("job_changed_next_7_days", "Job Changed Next 7 Days"),
]


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


class DashboardMonitorThread(Thread):
    def __init__(self, state):
        super().__init__(daemon=True)
        self.state = state
        self.stop_event = Event()

    def run(self):
        while not self.stop_event.is_set():
            self.state.refresh_dashboard()
            settings = self.state.get_settings(include_secret=True)
            interval = max(5, int(settings.get("alerts", {}).get("poll_seconds", 60)))
            self.stop_event.wait(interval)


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
        views = rms.get("views", {})
        self.api_base_input = QLineEdit(rms.get("api_base", "https://api.current-rms.com/api/v1"))
        self.subdomain_input = QLineEdit(rms.get("subdomain", ""))
        self.api_key_input = QLineEdit(rms.get("api_key", ""))
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.per_page_input = QSpinBox()
        self.per_page_input.setRange(1, 500)
        self.per_page_input.setValue(int(rms.get("per_page", 48)))
        self.max_pages_input = QSpinBox()
        self.max_pages_input.setRange(1, 20)
        self.max_pages_input.setValue(int(rms.get("max_pages", 2)))

        self.view_inputs = {
            "today_out": QLineEdit(str(views.get("today_out", ""))),
            "today_in": QLineEdit(str(views.get("today_in", ""))),
            "tomorrow_out": QLineEdit(str(views.get("tomorrow_out", ""))),
            "tomorrow_in": QLineEdit(str(views.get("tomorrow_in", ""))),
            "prep": QLineEdit(str(views.get("prep", ""))),
            "outstanding": QLineEdit(str(views.get("outstanding", ""))),
        }
        self.excluded_items_input = QLineEdit(", ".join(str(item) for item in rms.get("excluded_item_ids", [])))

        form.addRow("API base URL", self.api_base_input)
        form.addRow("Subdomain", self.subdomain_input)
        form.addRow("API key", self.api_key_input)
        form.addRow("Rows per page", self.per_page_input)
        form.addRow("Max pages", self.max_pages_input)
        form.addRow("Today out view", self.view_inputs["today_out"])
        form.addRow("Today in view", self.view_inputs["today_in"])
        form.addRow("Tomorrow out view", self.view_inputs["tomorrow_out"])
        form.addRow("Tomorrow in view", self.view_inputs["tomorrow_in"])
        form.addRow("Prep / next 7 days view", self.view_inputs["prep"])
        form.addRow("Outstanding view", self.view_inputs["outstanding"])
        form.addRow("Prep excluded item IDs", self.excluded_items_input)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        save_btn = QPushButton("Save API Details Locally")
        test_btn = QPushButton("Test Current RMS Connection")
        refresh_btn = QPushButton("Refresh Dashboard Now")
        save_btn.clicked.connect(self.save)
        test_btn.clicked.connect(self.test)
        refresh_btn.clicked.connect(self.refresh_now)
        buttons.addWidget(save_btn)
        buttons.addWidget(test_btn)
        buttons.addWidget(refresh_btn)
        layout.addLayout(buttons)

        note = QLabel(
            "API details and view IDs are stored only in manager_data/settings.json on this PC. "
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
            "per_page": self.per_page_input.value(),
            "max_pages": self.max_pages_input.value(),
            "views": {key: field.text().strip() for key, field in self.view_inputs.items()},
            "excluded_item_ids": [
                item.strip()
                for item in self.excluded_items_input.text().split(",")
                if item.strip()
            ],
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

    def refresh_now(self):
        self.state.save_settings({"current_rms": self.settings_payload()})
        self.state.refresh_dashboard()
        QMessageBox.information(self, "Refreshed", "The manager has refreshed the dashboard data and alert state.")


class AlertsTab(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        layout = QVBoxLayout(self)
        settings = self.state.get_settings(include_secret=True).get("alerts", {})
        event_types = settings.get("event_types", {})

        form = QFormLayout()
        self.poll_seconds_input = QSpinBox()
        self.poll_seconds_input.setRange(5, 3600)
        self.poll_seconds_input.setValue(int(settings.get("poll_seconds", 60)))
        self.startup_suppress_input = QSpinBox()
        self.startup_suppress_input.setRange(0, 300)
        self.startup_suppress_input.setValue(int(settings.get("startup_sound_suppress_seconds", 20)))
        self.quiet_start_input = QSpinBox()
        self.quiet_start_input.setRange(0, 23)
        self.quiet_start_input.setValue(int(settings.get("quiet_hours_start", 21)))
        self.quiet_end_input = QSpinBox()
        self.quiet_end_input.setRange(0, 23)
        self.quiet_end_input.setValue(int(settings.get("quiet_hours_end", 7)))
        self.history_limit_input = QSpinBox()
        self.history_limit_input.setRange(10, 5000)
        self.history_limit_input.setValue(int(settings.get("history_limit", 500)))

        form.addRow("Refresh Current RMS every (sec)", self.poll_seconds_input)
        form.addRow("Suppress startup sounds for (sec)", self.startup_suppress_input)
        form.addRow("Quiet hours start (24h)", self.quiet_start_input)
        form.addRow("Quiet hours end (24h)", self.quiet_end_input)
        form.addRow("Notification history limit", self.history_limit_input)
        layout.addLayout(form)

        grid = QGridLayout()
        grid.addWidget(QLabel("Alert Type"), 0, 0)
        grid.addWidget(QLabel("Enabled"), 0, 1)
        grid.addWidget(QLabel("Popup"), 0, 2)
        grid.addWidget(QLabel("Sound"), 0, 3)
        grid.addWidget(QLabel("Sound File"), 0, 4)

        self.event_inputs = {}
        for row, (event_key, label) in enumerate(ALERT_LABELS, start=1):
            config = event_types.get(event_key, {})
            enabled = QCheckBox()
            enabled.setChecked(bool(config.get("enabled", True)))
            popup = QCheckBox()
            popup.setChecked(bool(config.get("show_popup", True)))
            sound = QCheckBox()
            sound.setChecked(bool(config.get("play_sound", True)))
            sound_name = QLineEdit(str(config.get("sound", "")))

            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(enabled, row, 1, alignment=Qt.AlignCenter)
            grid.addWidget(popup, row, 2, alignment=Qt.AlignCenter)
            grid.addWidget(sound, row, 3, alignment=Qt.AlignCenter)
            grid.addWidget(sound_name, row, 4)

            self.event_inputs[event_key] = {
                "enabled": enabled,
                "show_popup": popup,
                "play_sound": sound,
                "sound": sound_name,
            }

        layout.addLayout(grid)

        note = QLabel(
            "Alerts are sent to all currently registered Pis. "
            "Sound files are looked up inside the repo's sounds folder on each Pi."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QHBoxLayout()
        save_btn = QPushButton("Save Alert Settings")
        refresh_btn = QPushButton("Apply and Refresh Now")
        save_btn.clicked.connect(self.save)
        refresh_btn.clicked.connect(self.apply_and_refresh)
        buttons.addWidget(save_btn)
        buttons.addWidget(refresh_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)

    def settings_payload(self):
        event_types = {}
        for event_key, inputs in self.event_inputs.items():
            event_types[event_key] = {
                "enabled": inputs["enabled"].isChecked(),
                "show_popup": inputs["show_popup"].isChecked(),
                "play_sound": inputs["play_sound"].isChecked(),
                "sound": inputs["sound"].text().strip(),
            }

        return {
            "poll_seconds": self.poll_seconds_input.value(),
            "startup_sound_suppress_seconds": self.startup_suppress_input.value(),
            "quiet_hours_start": self.quiet_start_input.value(),
            "quiet_hours_end": self.quiet_end_input.value(),
            "history_limit": self.history_limit_input.value(),
            "event_types": event_types,
        }

    def save(self):
        self.state.save_settings({"alerts": self.settings_payload()})
        QMessageBox.information(self, "Saved", "Alert settings saved locally on this PC.")

    def apply_and_refresh(self):
        self.state.save_settings({"alerts": self.settings_payload()})
        self.state.refresh_dashboard()
        QMessageBox.information(self, "Applied", "Alert settings were saved and the manager refreshed immediately.")


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
        self.resize(1120, 760)

        tabs = QTabWidget()
        tabs.addTab(ConnectionTab(state), "Connection")
        tabs.addTab(CurrentRMSTab(state), "Current RMS")
        tabs.addTab(AlertsTab(state), "Alerts")
        tabs.addTab(PiScreensTab(state), "Pi Screens")
        self.setCentralWidget(tabs)


def main():
    state = ManagerState()
    server = ServerThread(state)
    monitor = DashboardMonitorThread(state)
    server.start()
    monitor.start()

    app = QApplication(sys.argv)
    window = ManagerWindow(state)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

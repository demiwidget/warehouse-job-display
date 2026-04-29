import socket
import sys
import threading
import traceback
from threading import Event, Thread

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
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
            try:
                self.state.refresh_dashboard()
                settings = self.state.get_settings(include_secret=True)
                interval = max(5, int(settings.get("alerts", {}).get("poll_seconds", 60)))
            except Exception as error:
                self.state.log_exception("Manager", "Background dashboard monitor failed", error)
                interval = 30
            self.stop_event.wait(interval)


class ResilientApplication(QApplication):
    def __init__(self, args, state):
        super().__init__(args)
        self.state = state

    def notify(self, receiver, event):
        try:
            return super().notify(receiver, event)
        except Exception as error:
            self.state.log_exception("Manager", "Qt event handler failed", error)
            return False


def install_exception_hooks(state):
    def handle_exception(exc_type, error, tb):
        state.log_activity(
            "Manager",
            f"Unhandled exception: {error}",
            level="error",
            details={"traceback": "".join(traceback.format_exception(exc_type, error, tb))},
        )

    sys.excepthook = handle_exception

    if hasattr(threading, "excepthook"):
        def handle_thread_exception(args):
            state.log_activity(
                "Manager",
                f"Thread {args.thread.name if args.thread else 'unknown'} failed: {args.exc_value}",
                level="error",
                details={
                    "traceback": "".join(
                        traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
                    )
                },
            )

        threading.excepthook = handle_thread_exception


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
        self.api_workers_input = QSpinBox()
        self.api_workers_input.setRange(1, 24)
        self.api_workers_input.setValue(int(rms.get("api_workers", 12)))

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
        form.addRow("Parallel API requests", self.api_workers_input)
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
            "api_workers": self.api_workers_input.value(),
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

        test_box = QWidget()
        test_layout = QVBoxLayout(test_box)
        test_layout.setContentsMargins(0, 12, 0, 0)

        test_heading = QLabel("Test Notification")
        test_heading.setStyleSheet("font-size: 18px; font-weight: 700;")
        test_layout.addWidget(test_heading)

        test_form = QFormLayout()
        self.test_title_input = QLineEdit("Test Notification")
        self.test_message_input = QTextEdit()
        self.test_message_input.setPlaceholderText("Type the popup text you want to show on the Pis.")
        self.test_message_input.setMinimumHeight(120)
        self.test_sound_input = QLineEdit("job-today.wav")
        self.test_sound_enabled = QCheckBox("Play sound")
        self.test_sound_enabled.setChecked(True)

        test_form.addRow("Title", self.test_title_input)
        test_form.addRow("Message", self.test_message_input)
        test_form.addRow("Sound file", self.test_sound_input)
        test_form.addRow("", self.test_sound_enabled)
        test_layout.addLayout(test_form)

        test_buttons = QHBoxLayout()
        send_test_btn = QPushButton("Send Test Notification To All Pis")
        send_test_btn.clicked.connect(self.send_test_notification)
        test_buttons.addWidget(send_test_btn)
        test_buttons.addStretch(1)
        test_layout.addLayout(test_buttons)

        test_note = QLabel(
            "This uses the same popup route as the live Pi alerts and sends the message to all registered Pis."
        )
        test_note.setWordWrap(True)
        test_layout.addWidget(test_note)
        layout.addWidget(test_box)
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

    def send_test_notification(self):
        success, message = self.state.send_test_notification(
            title=self.test_title_input.text().strip(),
            message=self.test_message_input.toPlainText(),
            sound_name=self.test_sound_input.text().strip(),
            play_sound=self.test_sound_enabled.isChecked(),
        )
        if success:
            QMessageBox.information(self, "Test Notification", message)
        else:
            QMessageBox.warning(self, "Test Notification", message)


class PiScreensTab(QWidget):
    COLUMNS = ["ID", "Name", "IP", "Screen", "Version", "State", "Activity", "Last Seen"]
    STATUS_COLORS = {
        "Online": "#2e7d32",
        "Display Restarting": "#f9a825",
        "Display Starting": "#1e88e5",
        "Rebooting": "#ef6c00",
        "Renaming": "#8e24aa",
        "Switching Screen": "#6d4c41",
        "Updating": "#00897b",
        "Update Failed": "#b71c1c",
        "Offline": "#616161",
        "Unknown": "#455a64",
    }

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
            ("Show Notification History", "notifications"),
        ):
            btn = QPushButton(label)
            btn.clicked.connect(lambda _checked=False, target=screen: self.send_screen(target))
            screen_buttons.addWidget(btn)
        layout.addLayout(screen_buttons)

        command_buttons = QHBoxLayout()
        rename_btn = QPushButton("Rename Pi")
        restart_btn = QPushButton("Restart Display App")
        update_btn = QPushButton("Update Pi From GitHub")
        reboot_btn = QPushButton("Reboot Pi")
        refresh_btn = QPushButton("Refresh List")
        rename_btn.clicked.connect(self.rename_selected_pi)
        restart_btn.clicked.connect(lambda: self.send_action("restart"))
        update_btn.clicked.connect(lambda: self.send_action("update"))
        reboot_btn.clicked.connect(lambda: self.send_action("reboot"))
        refresh_btn.clicked.connect(self.refresh)
        command_buttons.addWidget(rename_btn)
        command_buttons.addWidget(restart_btn)
        command_buttons.addWidget(update_btn)
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

    def selected_devices(self):
        rows = {index.row() for index in self.table.selectedIndexes()}
        devices = []
        for row in sorted(rows):
            device_id_item = self.table.item(row, 0)
            device_name_item = self.table.item(row, 1)
            if not device_id_item:
                continue
            devices.append(
                {
                    "id": device_id_item.text(),
                    "name": device_name_item.text() if device_name_item else "",
                }
            )
        return devices

    def refresh(self):
        devices = self.state.list_devices()
        self.table.setRowCount(len(devices))
        online_count = 0
        offline_count = 0
        for row, device in enumerate(devices):
            values = [
                device.get("id", ""),
                device.get("name", ""),
                device.get("ip", ""),
                device.get("screen", ""),
                device.get("version", ""),
                device.get("state", ""),
                device.get("activity", ""),
                device.get("last_seen", ""),
            ]
            state_value = str(device.get("state", "")).strip()
            if state_value == "Offline":
                offline_count += 1
            elif state_value:
                online_count += 1
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if self.COLUMNS[column] == "State":
                    color = self.STATUS_COLORS.get(str(value), "")
                    if color:
                        item.setBackground(QColor(color))
                        item.setForeground(QColor("#ffffff"))
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self.status.setText(f"{len(devices)} Pi screen(s) registered. {online_count} active / {offline_count} offline.")

    def send_screen(self, screen):
        self.send_action("set_screen", screen=screen)

    def rename_selected_pi(self):
        devices = self.selected_devices()
        if not devices:
            QMessageBox.warning(self, "No Pi Selected", "Select one Pi screen first.")
            return
        if len(devices) != 1:
            QMessageBox.warning(self, "Select One Pi", "Rename works on one Pi screen at a time.")
            return

        device = devices[0]
        current_name = device.get("name", "").strip()
        new_name, accepted = QInputDialog.getText(
            self,
            "Rename Pi",
            "Enter the new screen name:",
            text=current_name,
        )
        if not accepted:
            return

        clean_name = str(new_name or "").strip()
        if not clean_name:
            QMessageBox.warning(self, "Invalid Name", "Enter a non-empty name for this Pi screen.")
            return

        self.state.queue_command([device["id"]], "rename", device_name=clean_name)
        self.status.setText(f"Queued rename for {device['id']} to '{clean_name}'.")

    def send_action(self, action, screen=None):
        device_ids = self.selected_device_ids()
        if not device_ids:
            QMessageBox.warning(self, "No Pi Selected", "Select one or more Pi screens first.")
            return

        self.state.queue_command(device_ids, action, screen=screen)
        self.status.setText(f"Queued {action} for {len(device_ids)} Pi screen(s).")


class ActivityConsoleTab(QWidget):
    COLUMNS = ["Time", "Level", "Category", "Message"]
    LEVEL_COLORS = {
        "error": "#b71c1c",
        "warning": "#f57f17",
        "info": "#1b5e20",
    }

    def __init__(self, state):
        super().__init__()
        self.state = state
        layout = QVBoxLayout(self)

        controls = QHBoxLayout()
        self.category_filter = QComboBox()
        self.category_filter.addItems(["All", "Current RMS", "Pis", "Notifications", "Updates", "Commands", "Settings", "Manager"])
        self.level_filter = QComboBox()
        self.level_filter.addItems(["All", "info", "warning", "error"])
        refresh_btn = QPushButton("Refresh")
        clear_btn = QPushButton("Clear")
        copy_btn = QPushButton("Copy Diagnostics")
        refresh_btn.clicked.connect(self.refresh)
        clear_btn.clicked.connect(self.clear_log)
        copy_btn.clicked.connect(self.copy_diagnostics)
        self.category_filter.currentTextChanged.connect(self.refresh)
        self.level_filter.currentTextChanged.connect(self.refresh)

        controls.addWidget(QLabel("Category"))
        controls.addWidget(self.category_filter)
        controls.addWidget(QLabel("Level"))
        controls.addWidget(self.level_filter)
        controls.addWidget(refresh_btn)
        controls.addWidget(copy_btn)
        controls.addStretch(1)
        controls.addWidget(clear_btn)
        layout.addLayout(controls)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.MultiSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

        self.status = QLabel()
        layout.addWidget(self.status)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(2000)
        self.refresh()

    def refresh(self):
        entries = self.state.list_activity(
            category=self.category_filter.currentText(),
            level=self.level_filter.currentText(),
            limit=500,
        )
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            values = [
                entry.get("ts", ""),
                str(entry.get("level", "")).upper(),
                entry.get("category", ""),
                entry.get("message", ""),
            ]
            level_color = self.LEVEL_COLORS.get(str(entry.get("level", "")).lower(), "")
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if column == 1 and level_color:
                    item.setBackground(QColor(level_color))
                    item.setForeground(QColor("#ffffff"))
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        if self.table.columnCount() >= 4:
            self.table.setColumnWidth(3, 560)
        self.status.setText(f"Showing {len(entries)} event(s). Newest events are at the top.")

    def clear_log(self):
        if QMessageBox.question(self, "Clear Console", "Clear the local manager activity log?") != QMessageBox.Yes:
            return
        self.state.clear_activity()
        self.refresh()

    def copy_diagnostics(self):
        entries = self.state.list_activity(
            category=self.category_filter.currentText(),
            level=self.level_filter.currentText(),
            limit=500,
        )
        lines = [
            f"{entry.get('ts', '')}\t{str(entry.get('level', '')).upper()}\t{entry.get('category', '')}\t{entry.get('message', '')}"
            for entry in entries
        ]
        QApplication.clipboard().setText("\n".join(lines))
        self.status.setText(f"Copied {len(lines)} event(s) to the clipboard.")


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
        tabs.addTab(ActivityConsoleTab(state), "Console")
        self.setCentralWidget(tabs)

    def closeEvent(self, event):
        choice = QMessageBox.question(
            self,
            "Close Manager?",
            "Closing the manager stops the dashboard data server for the Pis. Are you sure you want to close it?",
        )
        if choice == QMessageBox.Yes:
            event.accept()
            return
        event.ignore()


def main():
    state = ManagerState()
    install_exception_hooks(state)
    server = ServerThread(state)
    monitor = DashboardMonitorThread(state)
    server.start()
    monitor.start()

    try:
        app = ResilientApplication(sys.argv, state)
        window = ManagerWindow(state)
        window.show()
        return app.exec()
    except Exception as error:
        state.log_exception("Manager", "Manager app crashed", error)
        return 1
    finally:
        monitor.stop_event.set()


if __name__ == "__main__":
    sys.exit(main())

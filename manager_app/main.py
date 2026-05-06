import shutil
import socket
import sys
import threading
import traceback
from pathlib import Path
from threading import Event, Thread

from PySide6.QtCore import QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
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
from manager_app.settings_store import DATA_DIR, PROJECT_ROOT
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

SOUNDS_DIR = PROJECT_ROOT / "sounds"
MANAGER_EXIT_FLAG = DATA_DIR / "allow_manager_exit.flag"
PI_BOOTSTRAP_URL = (
    "https://raw.githubusercontent.com/demiwidget/warehouse-job-display/main/scripts/bootstrap_pi.sh"
)
MANAGER_PI_BOOTSTRAP_URL = (
    "https://raw.githubusercontent.com/demiwidget/warehouse-job-display/main/scripts/bootstrap_manager_pi.sh"
)


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


def pi_install_host(settings):
    server = settings.get("server", {})
    host = str(server.get("host", "")).strip()
    if host and host not in {"0.0.0.0", "::", "127.0.0.1", "localhost"}:
        return host

    for address in local_addresses():
        if not address.startswith("127."):
            return address
    return "MANAGER_PC_IP"


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


class UpdateMonitorThread(Thread):
    def __init__(self, state):
        super().__init__(daemon=True)
        self.state = state
        self.stop_event = Event()

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.state.refresh_update_status(force=True)
            except Exception as error:
                self.state.log_exception("Updates", "GitHub update monitor failed", error)
            self.stop_event.wait(300)


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

        layout.addWidget(QLabel("Standard Pi install/update command:"))
        self.install_command = QTextEdit()
        self.install_command.setReadOnly(True)
        self.install_command.setMinimumHeight(95)
        layout.addWidget(self.install_command)

        layout.addWidget(QLabel("Overwrite an old Node-RED/Home Assistant Pi:"))
        self.overwrite_install_command = QTextEdit()
        self.overwrite_install_command.setReadOnly(True)
        self.overwrite_install_command.setMinimumHeight(130)
        layout.addWidget(self.overwrite_install_command)

        layout.addWidget(QLabel("Trial Manager Pi install command:"))
        self.manager_pi_install_command = QTextEdit()
        self.manager_pi_install_command.setReadOnly(True)
        self.manager_pi_install_command.setMinimumHeight(90)
        layout.addWidget(self.manager_pi_install_command)

        copy_buttons = QHBoxLayout()
        copy_install_btn = QPushButton("Copy Standard Install")
        copy_overwrite_btn = QPushButton("Copy Old-System Install")
        copy_manager_pi_btn = QPushButton("Copy Manager Pi Install")
        copy_install_btn.clicked.connect(
            lambda: self.copy_command(self.install_command, "Copied the standard Pi install command.")
        )
        copy_overwrite_btn.clicked.connect(
            lambda: self.copy_command(self.overwrite_install_command, "Copied the old-system overwrite command.")
        )
        copy_manager_pi_btn.clicked.connect(
            lambda: self.copy_command(self.manager_pi_install_command, "Copied the Manager Pi install command.")
        )
        copy_buttons.addWidget(copy_install_btn)
        copy_buttons.addWidget(copy_overwrite_btn)
        copy_buttons.addWidget(copy_manager_pi_btn)
        copy_buttons.addStretch(1)
        layout.addLayout(copy_buttons)

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
        server = settings.get("server", {})
        port = server.get("port", 8765)
        if getattr(self.state, "is_remote", False):
            install_host = self.state.install_host()
            lines = [getattr(self.state, "base_url", f"http://{install_host}:{port}")]
        else:
            install_host = pi_install_host(settings)
            lines = [f"http://{address}:{port}" for address in local_addresses()]
        self.addresses.setPlainText("\n".join(lines))
        self.install_command.setPlainText(
            f"WAREHOUSE_MANAGER_IP={install_host} WAREHOUSE_MANAGER_PORT={port} "
            f"bash -c \"$(curl -fsSL {PI_BOOTSTRAP_URL} || wget -qO- {PI_BOOTSTRAP_URL})\""
        )
        self.overwrite_install_command.setPlainText(
            f"WAREHOUSE_MANAGER_IP={install_host} WAREHOUSE_MANAGER_PORT={port} "
            "WAREHOUSE_OVERWRITE_OLD_SYSTEM=1 WAREHOUSE_REBOOT_AFTER_INSTALL=1 "
            f"bash -c \"$(curl -fsSL {PI_BOOTSTRAP_URL} || wget -qO- {PI_BOOTSTRAP_URL})\""
        )
        self.manager_pi_install_command.setPlainText(
            "WAREHOUSE_REBOOT_AFTER_INSTALL=1 "
            f"bash -c \"$(curl -fsSL {MANAGER_PI_BOOTSTRAP_URL} || wget -qO- {MANAGER_PI_BOOTSTRAP_URL})\""
        )
        if getattr(self.state, "is_remote", False):
            self.status.setText("Connected to the Manager Pi. Connection changes take effect when its backend restarts.")
        else:
            self.status.setText("The manager server is running. Connection changes take effect next time the app starts.")

    def copy_command(self, widget, message):
        QApplication.clipboard().setText(widget.toPlainText())
        self.status.setText(message)

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
        QMessageBox.information(self, "Saved", "Connection settings saved. Restart the manager backend to use a changed port.")


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
        form.addRow("Prep / alert excluded item IDs", self.excluded_items_input)
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
            "API details and view IDs are stored only in manager_data/settings.json on the manager. "
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
        QMessageBox.information(self, "Saved", "Current RMS details saved on the manager.")

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
        grid.addWidget(QLabel("Test"), 0, 5)

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
            test_button = QPushButton("Test")
            test_button.clicked.connect(
                lambda _checked=False, key=event_key, text=label: self.send_category_test_notification(key, text)
            )

            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(enabled, row, 1, alignment=Qt.AlignCenter)
            grid.addWidget(popup, row, 2, alignment=Qt.AlignCenter)
            grid.addWidget(sound, row, 3, alignment=Qt.AlignCenter)
            grid.addWidget(sound_name, row, 4)
            grid.addWidget(test_button, row, 5)

            self.event_inputs[event_key] = {
                "enabled": enabled,
                "show_popup": popup,
                "play_sound": sound,
                "sound": sound_name,
                "test": test_button,
            }

        layout.addLayout(grid)

        note = QLabel(
            "Alerts are sent to all currently registered Pis. "
            "Sound files are served from this PC's sounds folder and refreshed on each Pi before playback."
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

        sound_buttons = QHBoxLayout()
        import_sound_btn = QPushButton("Import WAV Sound")
        open_sounds_btn = QPushButton("Open Sounds Folder")
        import_sound_btn.clicked.connect(self.import_sound_file)
        open_sounds_btn.clicked.connect(self.open_sounds_folder)
        sound_buttons.addWidget(import_sound_btn)
        sound_buttons.addWidget(open_sounds_btn)
        sound_buttons.addStretch(1)
        test_layout.addLayout(sound_buttons)

        target_heading = QLabel("Send Test To")
        target_heading.setStyleSheet("font-weight: 700;")
        test_layout.addWidget(target_heading)

        self.test_device_table = QTableWidget(0, 4)
        self.test_device_table.setHorizontalHeaderLabels(["Send", "Name", "IP", "State"])
        self.test_device_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.test_device_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.test_device_table.setMinimumHeight(150)
        test_layout.addWidget(self.test_device_table)

        test_buttons = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_none_btn = QPushButton("Select None")
        refresh_targets_btn = QPushButton("Refresh Pi Targets")
        send_test_btn = QPushButton("Send Test Notification To Selected Pis")
        select_all_btn.clicked.connect(lambda: self.set_all_test_targets(True))
        select_none_btn.clicked.connect(lambda: self.set_all_test_targets(False))
        refresh_targets_btn.clicked.connect(self.refresh_test_devices)
        send_test_btn.clicked.connect(self.send_test_notification)
        test_buttons.addWidget(select_all_btn)
        test_buttons.addWidget(select_none_btn)
        test_buttons.addWidget(refresh_targets_btn)
        test_buttons.addStretch(1)
        test_buttons.addWidget(send_test_btn)
        test_layout.addLayout(test_buttons)

        test_note = QLabel(
            "This uses the same popup route as the live Pi alerts, but only sends to the checked Pi screens above."
        )
        test_note.setWordWrap(True)
        test_layout.addWidget(test_note)
        layout.addWidget(test_box)
        layout.addStretch(1)
        self.refresh_test_devices()

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

    def current_test_target_checks(self):
        checks = {}
        for row in range(self.test_device_table.rowCount()):
            item = self.test_device_table.item(row, 0)
            if not item:
                continue
            device_id = str(item.data(Qt.UserRole) or "").strip()
            if device_id:
                checks[device_id] = item.checkState() == Qt.Checked
        return checks

    def refresh_test_devices(self):
        previous_checks = self.current_test_target_checks() if hasattr(self, "test_device_table") else {}
        devices = self.state.list_devices()
        self.test_device_table.setRowCount(len(devices))
        for row, device in enumerate(devices):
            device_id = str(device.get("id", "")).strip()
            send_item = QTableWidgetItem("")
            send_item.setFlags((send_item.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable)
            send_item.setCheckState(Qt.Checked if previous_checks.get(device_id, True) else Qt.Unchecked)
            send_item.setData(Qt.UserRole, device_id)
            self.test_device_table.setItem(row, 0, send_item)

            for column, value in enumerate(
                [
                    device.get("name", ""),
                    device.get("ip", ""),
                    device.get("state", ""),
                ],
                start=1,
            ):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.test_device_table.setItem(row, column, item)
        self.test_device_table.resizeColumnsToContents()

    def set_all_test_targets(self, checked):
        for row in range(self.test_device_table.rowCount()):
            item = self.test_device_table.item(row, 0)
            if item:
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def selected_test_device_ids(self):
        ids = []
        for row in range(self.test_device_table.rowCount()):
            item = self.test_device_table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                device_id = str(item.data(Qt.UserRole) or "").strip()
                if device_id:
                    ids.append(device_id)
        return ids

    def open_sounds_folder(self):
        if getattr(self.state, "is_remote", False):
            QMessageBox.information(
                self,
                "Remote Sounds Folder",
                "Sounds are stored on the Manager Pi. Use Import WAV Sound to upload from this PC.",
            )
            return
        SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(SOUNDS_DIR)))

    def import_sound_file(self):
        source_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Import WAV Sound",
            "",
            "WAV sound files (*.wav)",
        )
        if not source_path:
            return

        source = Path(source_path)
        if source.suffix.lower() != ".wav":
            QMessageBox.warning(self, "Import Sound", "Use a .wav file for reliable playback on the Pis.")
            return

        SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
        target = SOUNDS_DIR / source.name
        if target.exists():
            choice = QMessageBox.question(
                self,
                "Replace Sound?",
                f"{target.name} already exists. Replace it?",
            )
            if choice != QMessageBox.Yes:
                return

        try:
            if hasattr(self.state, "upload_sound"):
                uploaded_name = self.state.upload_sound(source)
                target = SOUNDS_DIR / uploaded_name
            else:
                shutil.copy2(source, target)
        except Exception as error:
            QMessageBox.warning(self, "Import Sound Failed", f"Could not import the sound file:\n{error}")
            return

        self.test_sound_input.setText(target.name)
        QMessageBox.information(
            self,
            "Sound Imported",
            (
                f"Imported {target.name} into the sounds folder.\n\n"
                "Use that exact filename in any alert sound box. Pis refresh sounds from this manager before playback. "
                "Push the file to GitHub as well if you want it included on new/rebuilt Pis."
            ),
        )

    def send_test_notification(self):
        device_ids = self.selected_test_device_ids()
        if not device_ids:
            QMessageBox.warning(self, "Test Notification", "Select at least one Pi screen to send the test to.")
            return

        success, message = self.state.send_test_notification(
            title=self.test_title_input.text().strip(),
            message=self.test_message_input.toPlainText(),
            sound_name=self.test_sound_input.text().strip(),
            play_sound=self.test_sound_enabled.isChecked(),
            device_ids=device_ids,
        )
        if success:
            QMessageBox.information(self, "Test Notification", message)
        else:
            QMessageBox.warning(self, "Test Notification", message)

    def send_category_test_notification(self, event_key, label):
        device_ids = self.selected_test_device_ids()
        if not device_ids:
            QMessageBox.warning(self, "Test Sound", "Select at least one Pi screen to send the test to.")
            return

        inputs = self.event_inputs.get(event_key, {})
        sound_name = inputs.get("sound").text().strip() if inputs.get("sound") else ""
        if not sound_name:
            QMessageBox.warning(self, "Test Sound", f"{label} does not have a sound file configured.")
            return

        success, message = self.state.send_test_notification(
            title=f"Test: {label}",
            message=f"Testing {label} sound file:\n{sound_name}",
            sound_name=sound_name,
            play_sound=True,
            device_ids=device_ids,
        )
        if success:
            QMessageBox.information(self, "Test Sound", message)
        else:
            QMessageBox.warning(self, "Test Sound", message)


class ManagerPiTab(QWidget):
    command_finished = Signal(str)

    def __init__(self, state):
        super().__init__()
        self.state = state
        layout = QVBoxLayout(self)

        heading = QLabel("Manager Pi Control")
        heading.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(heading)

        intro = QLabel(
            "These controls affect the Manager Pi backend, not the individual dashboard screen Pis. "
            "Use this page to update or restart the always-on Manager Pi."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.summary = QLabel("Loading Manager Pi status...")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("font-weight: 700;")
        layout.addWidget(self.summary)

        self.service_status = QLabel("")
        self.service_status.setWordWrap(True)
        layout.addWidget(self.service_status)

        self.security_status = QLabel("")
        self.security_status.setWordWrap(True)
        layout.addWidget(self.security_status)

        self.manager_update_status = QLabel("")
        self.manager_update_status.setWordWrap(True)
        layout.addWidget(self.manager_update_status)

        buttons = QHBoxLayout()
        check_btn = QPushButton("Check For Updates")
        update_btn = QPushButton("Update Manager Pi")
        restart_backend_btn = QPushButton("Restart Backend")
        restart_display_btn = QPushButton("Restart Status Display")
        reboot_btn = QPushButton("Reboot Manager Pi")

        check_btn.clicked.connect(lambda: self.run_command("check_updates"))
        update_btn.clicked.connect(lambda: self.run_command("update", confirm=True))
        restart_backend_btn.clicked.connect(lambda: self.run_command("restart_backend", confirm=True))
        restart_display_btn.clicked.connect(lambda: self.run_command("restart_display", confirm=True))
        reboot_btn.clicked.connect(lambda: self.run_command("reboot", confirm=True))

        buttons.addWidget(check_btn)
        buttons.addWidget(update_btn)
        buttons.addWidget(restart_backend_btn)
        buttons.addWidget(restart_display_btn)
        buttons.addWidget(reboot_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.command_status = QLabel("Ready.")
        self.command_status.setWordWrap(True)
        layout.addWidget(self.command_status)

        self.manager_update_log = QTextEdit()
        self.manager_update_log.setReadOnly(True)
        self.manager_update_log.setMinimumHeight(120)
        self.manager_update_log.setPlaceholderText("Manager Pi update log will appear here after an update starts.")
        layout.addWidget(self.manager_update_log)

        password_box = QGridLayout()
        password_heading = QLabel("Change Manager Pi Password")
        password_heading.setStyleSheet("font-size: 16px; font-weight: 700;")
        layout.addWidget(password_heading)

        self.current_password_input = QLineEdit()
        self.current_password_input.setEchoMode(QLineEdit.Password)
        self.current_password_input.setPlaceholderText("Current password or old legacy code")
        self.new_password_input = QLineEdit()
        self.new_password_input.setEchoMode(QLineEdit.Password)
        self.new_password_input.setPlaceholderText("New password, at least 8 characters")
        self.confirm_password_input = QLineEdit()
        self.confirm_password_input.setEchoMode(QLineEdit.Password)
        self.confirm_password_input.setPlaceholderText("Confirm new password")
        change_password_btn = QPushButton("Change Password")
        change_password_btn.clicked.connect(self.change_password)

        password_box.addWidget(QLabel("Current"), 0, 0)
        password_box.addWidget(self.current_password_input, 0, 1)
        password_box.addWidget(QLabel("New"), 1, 0)
        password_box.addWidget(self.new_password_input, 1, 1)
        password_box.addWidget(QLabel("Confirm"), 2, 0)
        password_box.addWidget(self.confirm_password_input, 2, 1)
        password_box.addWidget(change_password_btn, 3, 1)
        layout.addLayout(password_box)
        layout.addStretch(1)

        self.command_finished.connect(self.on_command_finished)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(5000)
        self.refresh()

    def refresh(self):
        try:
            status = self.state.get_manager_status()
        except Exception as error:
            self.summary.setText(f"Could not read Manager Pi status: {error}")
            self.service_status.setText("")
            return

        update_status = status.get("update_status", {}) or {}
        latest = str(update_status.get("latest_version") or "unknown")
        local = str(update_status.get("local_version") or status.get("version") or "unknown")
        checked_at = str(update_status.get("checked_at") or "not checked yet")
        error = str(update_status.get("error") or "").strip()
        if error:
            update_text = f"Update check failed: {error}"
        elif update_status.get("manager_update_available"):
            update_text = f"Update available: GitHub v{latest}, Manager Pi v{local}."
        else:
            update_text = f"Up to date: GitHub v{latest}, Manager Pi v{local}."

        role_text = "Connected to Manager Pi backend." if status.get("is_manager_pi") else "Manager Pi controls unavailable here."
        self.summary.setText(f"{role_text}\n{update_text}\nLast checked: {checked_at}.")
        self.service_status.setText(
            "Services: "
            f"backend={status.get('backend_service', 'unknown')}, "
            f"display={status.get('display_service', 'unknown')}, "
            f"update={status.get('update_service', 'unknown')}"
        )
        security = status.get("security", {}) or {}
        if security.get("legacy_code_active"):
            security_text = "Security: old legacy code is active. Change it to a private password below."
        elif security.get("password_set"):
            updated = str(security.get("updated_at") or "").strip()
            security_text = f"Security: password protected{f' since {updated}' if updated else ''}."
        else:
            security_text = "Security: initial password has not been confirmed yet."
        self.security_status.setText(security_text)

        manager_update = status.get("manager_update_status", {}) or {}
        if manager_update:
            progress = manager_update.get("progress", 0)
            state = str(manager_update.get("state", "")).strip()
            title = str(manager_update.get("title", "")).strip()
            detail = str(manager_update.get("detail", "")).strip()
            updated_at = str(manager_update.get("updated_at", "")).strip()
            self.manager_update_status.setText(
                f"Last Manager Pi update: {progress}% {state} - {title}. {detail} {updated_at}".strip()
            )
        else:
            self.manager_update_status.setText("Last Manager Pi update: no update log yet.")

        log_text = str(status.get("manager_update_log") or "").strip()
        if log_text and self.manager_update_log.toPlainText() != log_text:
            self.manager_update_log.setPlainText(log_text)
            self.manager_update_log.verticalScrollBar().setValue(self.manager_update_log.verticalScrollBar().maximum())

    def run_command(self, action, confirm=False):
        confirm_messages = {
            "update": "Update the Manager Pi from GitHub now? The backend may restart briefly.",
            "restart_backend": "Restart the Manager Pi backend now? The PC app may disconnect briefly.",
            "restart_display": "Restart the Manager Pi status display now?",
            "reboot": "Reboot the Manager Pi now? Dashboards will stop updating while it restarts.",
        }
        if confirm:
            choice = QMessageBox.question(self, "Confirm Manager Pi Action", confirm_messages.get(action, "Continue?"))
            if choice != QMessageBox.Yes:
                return

        self.command_status.setText(f"Sending Manager Pi command: {action}...")

        def worker():
            try:
                result = self.state.run_manager_command(action)
                message = str(result.get("message") or f"{action} sent.")
            except Exception as error:
                message = f"Manager Pi command failed: {error}"
            self.command_finished.emit(message)

        Thread(target=worker, daemon=True).start()

    def on_command_finished(self, message):
        self.command_status.setText(message)
        self.refresh()

    def change_password(self):
        current_password = self.current_password_input.text()
        new_password = self.new_password_input.text()
        confirm_password = self.confirm_password_input.text()

        if len(new_password) < 8:
            QMessageBox.warning(self, "Password Too Short", "Use at least 8 characters for the new Manager Pi password.")
            return
        if new_password != confirm_password:
            QMessageBox.warning(self, "Passwords Do Not Match", "The new password and confirmation do not match.")
            return

        try:
            self.state.change_admin_password(current_password, new_password)
        except Exception as error:
            QMessageBox.warning(self, "Password Change Failed", str(error))
            return

        self.current_password_input.clear()
        self.new_password_input.clear()
        self.confirm_password_input.clear()
        self.command_status.setText("Manager Pi password changed.")
        QMessageBox.information(self, "Password Changed", "Manager Pi password changed successfully.")
        self.refresh()


class PiScreensTab(QWidget):
    COLUMNS = ["ID", "Name", "IP", "Screen", "Version", "Update", "State", "Activity", "Last Seen"]
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

        self.update_status = QLabel("Checking GitHub update status...")
        self.update_status.setWordWrap(True)
        self.update_status.setStyleSheet("font-weight: 700;")
        layout.addWidget(self.update_status)

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
        check_updates_btn = QPushButton("Check GitHub Updates")
        reboot_btn = QPushButton("Reboot Pi")
        remove_btn = QPushButton("Remove Selected")
        refresh_btn = QPushButton("Refresh List")
        rename_btn.clicked.connect(self.rename_selected_pi)
        restart_btn.clicked.connect(lambda: self.send_action("restart"))
        update_btn.clicked.connect(lambda: self.send_action("update"))
        check_updates_btn.clicked.connect(self.check_updates_now)
        reboot_btn.clicked.connect(lambda: self.send_action("reboot"))
        remove_btn.clicked.connect(self.remove_selected_pis)
        refresh_btn.clicked.connect(self.refresh)
        command_buttons.addWidget(rename_btn)
        command_buttons.addWidget(restart_btn)
        command_buttons.addWidget(update_btn)
        command_buttons.addWidget(reboot_btn)
        command_buttons.addWidget(remove_btn)
        command_buttons.addStretch(1)
        command_buttons.addWidget(check_updates_btn)
        command_buttons.addWidget(refresh_btn)
        layout.addLayout(command_buttons)

        self.status = QLabel("Waiting for Pi screens to register...")
        layout.addWidget(self.status)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(3000)
        self.refresh()
        self.check_updates_now()

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
        update_status = self.state.get_update_status()
        self.table.setRowCount(len(devices))
        online_count = 0
        offline_count = 0
        update_count = 0
        for row, device in enumerate(devices):
            values = [
                device.get("id", ""),
                device.get("name", ""),
                device.get("ip", ""),
                device.get("screen", ""),
                device.get("version", ""),
                device.get("update", ""),
                device.get("state", ""),
                device.get("activity", ""),
                device.get("last_seen", ""),
            ]
            state_value = str(device.get("state", "")).strip()
            update_value = str(device.get("update", "")).strip()
            if state_value == "Offline":
                offline_count += 1
            elif state_value:
                online_count += 1
            if update_value.startswith("Available"):
                update_count += 1
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if self.COLUMNS[column] == "State":
                    color = self.STATUS_COLORS.get(str(value), "")
                    if color:
                        item.setBackground(QColor(color))
                        item.setForeground(QColor("#ffffff"))
                elif self.COLUMNS[column] == "Update" and str(value).startswith("Available"):
                    item.setBackground(QColor("#f9a825"))
                    item.setForeground(QColor("#111111"))
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self.update_status.setText(self.format_update_status(update_status))
        self.status.setText(
            f"{len(devices)} Pi screen(s) registered. {online_count} active / {offline_count} offline. "
            f"{update_count} update(s) available."
        )

    def format_update_status(self, update_status):
        checked_at = str(update_status.get("checked_at") or "not checked yet")
        latest = str(update_status.get("latest_version") or "unknown")
        local = str(update_status.get("local_version") or "unknown")
        error = str(update_status.get("error") or "").strip()
        if error:
            return f"GitHub update check failed: {error} Last checked: {checked_at}."
        if update_status.get("manager_update_available"):
            return f"Manager update available: GitHub v{latest}, this manager v{local}. Restart the manager to apply it."
        return f"GitHub latest version: v{latest}. Manager running v{local}. Last checked: {checked_at}."

    def check_updates_now(self):
        self.update_status.setText("Checking GitHub for updates...")
        Thread(target=lambda: self.state.refresh_update_status(force=True), daemon=True).start()

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

    def remove_selected_pis(self):
        devices = self.selected_devices()
        if not devices:
            QMessageBox.warning(self, "No Pi Selected", "Select one or more Pi screens to remove.")
            return

        names = ", ".join(device.get("name") or device.get("id", "") for device in devices)
        choice = QMessageBox.question(
            self,
            "Remove Pi Screens?",
            (
                f"Remove {len(devices)} Pi screen(s) from the manager list?\n\n"
                f"{names}\n\n"
                "If a removed Pi is still running the dashboard app, it will register again automatically."
            ),
        )
        if choice != QMessageBox.Yes:
            return

        removed_count = self.state.remove_devices([device["id"] for device in devices])
        self.status.setText(f"Removed {removed_count} Pi screen(s) from the manager list.")
        self.refresh()

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
        self.category_filter.addItems(["All", "Current RMS", "Pis", "Audio", "Notifications", "Updates", "Commands", "Settings", "Manager"])
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
        self.confirmed_close = False
        self.setWindowTitle("Warehouse Dashboard Manager")
        self.resize(1120, 760)

        tabs = QTabWidget()
        tabs.addTab(ConnectionTab(state), "Connection")
        tabs.addTab(CurrentRMSTab(state), "Current RMS")
        tabs.addTab(AlertsTab(state), "Alerts")
        tabs.addTab(ManagerPiTab(state), "Manager Pi")
        tabs.addTab(PiScreensTab(state), "Pi Screens")
        tabs.addTab(ActivityConsoleTab(state), "Console")
        self.setCentralWidget(tabs)

    def closeEvent(self, event):
        if getattr(self.state, "is_remote", False):
            event.accept()
            return

        choice = QMessageBox.question(
            self,
            "Close Manager?",
            "Closing the manager stops the dashboard data server for the Pis. Are you sure you want to close it?",
        )
        if choice == QMessageBox.Yes:
            self.confirmed_close = True
            try:
                MANAGER_EXIT_FLAG.parent.mkdir(parents=True, exist_ok=True)
                MANAGER_EXIT_FLAG.write_text("confirmed", encoding="utf-8")
                self.state.log_activity("Manager", "Manager app closed by user confirmation.")
            except Exception as error:
                self.state.log_exception("Manager", "Could not write confirmed close marker", error)
            event.accept()
            return
        event.ignore()


def main():
    state = ManagerState()
    install_exception_hooks(state)
    server = ServerThread(state)
    monitor = DashboardMonitorThread(state)
    update_monitor = UpdateMonitorThread(state)
    server.start()
    monitor.start()
    update_monitor.start()

    window = None
    try:
        app = ResilientApplication(sys.argv, state)
        app.setQuitOnLastWindowClosed(True)
        window = ManagerWindow(state)
        window.show()
        exit_code = app.exec()
        if window and window.confirmed_close:
            return exit_code
        state.log_activity("Manager", f"Manager event loop exited unexpectedly with code {exit_code}.", level="warning")
        return 1
    except Exception as error:
        state.log_exception("Manager", "Manager app crashed", error)
        return 1
    finally:
        monitor.stop_event.set()
        update_monitor.stop_event.set()


if __name__ == "__main__":
    sys.exit(main())

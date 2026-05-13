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
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
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

APP_STYLESHEET = """
QMainWindow {
    background: #0e1216;
}
QWidget {
    color: #edf4f7;
    font-family: "Segoe UI", "Aptos", "Verdana";
    font-size: 12px;
}
QWidget#WarehousePage {
    background: #0e1216;
}
QScrollArea {
    background: #0e1216;
    border: 0;
}
QScrollBar:vertical {
    background: #0b0f13;
    width: 12px;
    margin: 2px;
    border-radius: 6px;
}
QScrollBar::handle:vertical {
    background: #2f4652;
    border-radius: 6px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: #57d68d;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}
QTabWidget::pane {
    border-top: 1px solid #2b3a43;
    background: #0e1216;
}
QTabBar::tab {
    background: #141b20;
    color: #d7e3e8;
    border: 1px solid #263640;
    border-bottom-color: #2b3a43;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 7px 14px;
    margin-right: 3px;
    font-weight: 750;
}
QTabBar::tab:selected {
    background: #57d68d;
    color: #04130b;
    border-color: #57d68d;
}
QTabBar::tab:hover:!selected {
    background: #1c2a32;
    color: #f5fbff;
}
QLabel {
    color: #edf4f7;
    background: transparent;
}
QLabel#PageTitle {
    font-size: 21px;
    font-weight: 900;
    color: #f7fbff;
}
QLabel#PageIntro {
    color: #a9bac3;
    font-size: 12px;
    font-weight: 600;
}
QLabel#SectionTitle {
    color: #f7fbff;
    font-size: 15px;
    font-weight: 900;
}
QLabel#SectionSubtitle {
    color: #9fb0b8;
    font-weight: 600;
}
QLabel#StatusStrip {
    background: #101820;
    border: 1px solid #2b3a43;
    border-radius: 8px;
    color: #c8d6dd;
    font-weight: 800;
    padding: 7px;
}
QFrame#WarehousePanel,
QFrame#ManagerSection {
    background: #141b20;
    border: 1px solid #2b3a43;
    border-radius: 12px;
}
QFrame#ToolbarPanel {
    background: #111920;
    border: 1px solid #2b3a43;
    border-radius: 12px;
}
QLineEdit,
QTextEdit,
QPlainTextEdit,
QSpinBox,
QComboBox {
    background: #0b0f13;
    color: #f5fbff;
    border: 1px solid #3c515d;
    border-radius: 7px;
    padding: 5px;
    selection-background-color: #57d68d;
    selection-color: #04130b;
}
QLineEdit:focus,
QTextEdit:focus,
QPlainTextEdit:focus,
QSpinBox:focus,
QComboBox:focus {
    border-color: #57d68d;
}
QLineEdit:disabled,
QTextEdit:disabled,
QSpinBox:disabled,
QComboBox:disabled {
    color: #73828a;
    border-color: #1d2a31;
}
QTextEdit {
    line-height: 1.35em;
}
QComboBox::drop-down {
    border-left: 1px solid #2b3a43;
    width: 24px;
}
QPushButton {
    background: #22313a;
    color: #f5fbff;
    border: 1px solid #3c515d;
    border-radius: 8px;
    padding: 6px 10px;
    font-weight: 800;
}
QPushButton:hover {
    background: #2d414d;
    border-color: #5f7a88;
}
QPushButton:pressed {
    background: #17232b;
}
QPushButton#PrimaryAction {
    background: #57d68d;
    color: #04130b;
    border-color: #57d68d;
}
QPushButton#PrimaryAction:hover {
    background: #6ee6a0;
}
QPushButton#DangerAction {
    background: #793238;
    color: #fff4f4;
    border-color: #a84a52;
}
QPushButton#DangerAction:hover {
    background: #93414a;
}
QPushButton#QuietAction {
    background: #17232b;
    color: #c9d7dd;
}
QCheckBox {
    background: transparent;
    color: #edf4f7;
    spacing: 6px;
    font-weight: 650;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 5px;
    border: 1px solid #4a6270;
    background: #0b0f13;
}
QCheckBox::indicator:checked {
    background: #57d68d;
    border-color: #57d68d;
}
QTableWidget {
    background: #0b0f13;
    alternate-background-color: #111a20;
    color: #f5fbff;
    gridline-color: #263640;
    border: 1px solid #2b3a43;
    border-radius: 10px;
    selection-background-color: #244d3a;
    selection-color: #f7fbff;
}
QTableWidget::item {
    padding: 5px;
    border-bottom: 1px solid #17232b;
}
QTableWidget::item:selected {
    background: #244d3a;
}
QHeaderView::section {
    background: #18252d;
    color: #83c5d8;
    border: 0;
    border-right: 1px solid #2b3a43;
    border-bottom: 1px solid #2b3a43;
    padding: 6px;
    font-weight: 900;
}
QMessageBox {
    background: #141b20;
}
"""


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


def make_scroll_page(parent, margins=(12, 12, 12, 14), spacing=10):
    parent.setObjectName("WarehousePage")
    outer_layout = QVBoxLayout(parent)
    outer_layout.setContentsMargins(0, 0, 0, 0)
    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_area.setFrameShape(QFrame.NoFrame)
    scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll_area.verticalScrollBar().setSingleStep(34)
    outer_layout.addWidget(scroll_area)

    content = QWidget()
    content.setObjectName("WarehousePage")
    scroll_area.setWidget(content)
    layout = QVBoxLayout(content)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    parent.scroll_area = scroll_area
    parent.scroll_content = content
    return layout


def add_page_heading(layout, title, intro=""):
    heading = QLabel(title)
    heading.setObjectName("PageTitle")
    layout.addWidget(heading)
    if intro:
        intro_label = QLabel(intro)
        intro_label.setObjectName("PageIntro")
        intro_label.setWordWrap(True)
        layout.addWidget(intro_label)


def make_panel(title="", subtitle=""):
    frame = QFrame()
    frame.setObjectName("WarehousePanel")
    panel_layout = QVBoxLayout(frame)
    panel_layout.setContentsMargins(12, 10, 12, 10)
    panel_layout.setSpacing(8)
    if title:
        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        panel_layout.addWidget(title_label)
    if subtitle:
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("SectionSubtitle")
        subtitle_label.setWordWrap(True)
        panel_layout.addWidget(subtitle_label)
    return frame, panel_layout


def make_toolbar_panel():
    frame = QFrame()
    frame.setObjectName("ToolbarPanel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(8)
    return frame, layout


def mark_primary(button):
    button.setObjectName("PrimaryAction")
    return button


def mark_danger(button):
    button.setObjectName("DangerAction")
    return button


def mark_quiet(button):
    button.setObjectName("QuietAction")
    return button


def make_status_label(text=""):
    label = QLabel(text)
    label.setObjectName("StatusStrip")
    label.setWordWrap(True)
    return label


def tune_table(table):
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(True)
    table.setWordWrap(False)
    return table


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
        layout = make_scroll_page(self)
        add_page_heading(
            layout,
            "Connection & Install",
            "Network settings and live one-command installers for dashboard Pis and Manager Pi trials.",
        )

        settings = self.state.get_settings(include_secret=True)
        server = settings.get("server", {})

        server_panel, server_layout = make_panel(
            "Manager Server",
            "These settings control where dashboard Pis connect for data, alerts, and commands.",
        )
        form = QFormLayout()
        self.host_input = QLineEdit(server.get("host", "0.0.0.0"))
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(int(server.get("port", 8765)))
        form.addRow("Listen address", self.host_input)
        form.addRow("Port", self.port_input)
        server_layout.addLayout(form)

        save_btn = mark_primary(QPushButton("Save Connection Settings"))
        save_btn.clicked.connect(self.save)
        server_layout.addWidget(save_btn)
        layout.addWidget(server_panel)

        address_panel, address_layout = make_panel(
            "Manager Addresses",
            "Use one of these addresses when installing or reconnecting a dashboard Pi.",
        )
        self.addresses = QTextEdit()
        self.addresses.setReadOnly(True)
        self.addresses.setMinimumHeight(105)
        address_layout.addWidget(self.addresses)
        layout.addWidget(address_panel)

        install_panel, install_layout = make_panel(
            "One-Command Installs",
            "These commands are generated live from the current Manager address and GitHub bootstrap scripts.",
        )
        install_layout.addWidget(QLabel("Standard Pi install/update command:"))
        self.install_command = QTextEdit()
        self.install_command.setReadOnly(True)
        self.install_command.setMinimumHeight(76)
        install_layout.addWidget(self.install_command)

        install_layout.addWidget(QLabel("Overwrite an old Node-RED/Home Assistant Pi:"))
        self.overwrite_install_command = QTextEdit()
        self.overwrite_install_command.setReadOnly(True)
        self.overwrite_install_command.setMinimumHeight(104)
        install_layout.addWidget(self.overwrite_install_command)

        install_layout.addWidget(QLabel("Trial Manager Pi install command:"))
        self.manager_pi_install_command = QTextEdit()
        self.manager_pi_install_command.setReadOnly(True)
        self.manager_pi_install_command.setMinimumHeight(72)
        install_layout.addWidget(self.manager_pi_install_command)

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
        install_layout.addLayout(copy_buttons)
        layout.addWidget(install_panel)

        self.status = make_status_label()
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
    @staticmethod
    def format_department_mappings(mappings):
        return "\n".join(
            f"{key} = {value}"
            for key, value in sorted((mappings or {}).items(), key=lambda item: str(item[0]))
        )

    @staticmethod
    def parse_department_mappings(text):
        mappings = {}
        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            separator = None
            for candidate in ("=", ":", ","):
                if candidate in line:
                    separator = candidate
                    break
            if separator:
                key, value = line.split(separator, 1)
            else:
                parts = line.split(None, 1)
                if len(parts) != 2:
                    continue
                key, value = parts
            key = key.strip()
            value = value.strip()
            if key and value:
                mappings[key] = value
        return mappings

    @staticmethod
    def parse_csv_ids(text):
        return [item.strip() for item in str(text or "").split(",") if item.strip()]

    def __init__(self, state):
        super().__init__()
        self.state = state
        layout = make_scroll_page(self)
        add_page_heading(
            layout,
            "Current RMS",
            "API connection, job view IDs, excluded items, and quarantine leaderboard settings.",
        )

        rms_panel, rms_layout = make_panel(
            "API Details & Dashboard Views",
            "Secrets stay in the manager data folder only; they are not written into the GitHub repo.",
        )
        form = QFormLayout()

        rms = self.state.get_settings(include_secret=True).get("current_rms", {})
        views = rms.get("views", {})
        quarantines = rms.get("quarantines", {}) or {}
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
        self.quarantine_enabled_input = QCheckBox()
        self.quarantine_enabled_input.setChecked(bool(quarantines.get("enabled", True)))
        self.quarantine_field_input = QLineEdit(
            str(quarantines.get("department_field", "department_responsible_for_repair"))
        )
        self.quarantine_per_page_input = QSpinBox()
        self.quarantine_per_page_input.setRange(1, 500)
        self.quarantine_per_page_input.setValue(int(quarantines.get("per_page", 100)))
        self.quarantine_max_pages_input = QSpinBox()
        self.quarantine_max_pages_input.setRange(1, 100)
        self.quarantine_max_pages_input.setValue(int(quarantines.get("max_pages", 20)))
        self.quarantine_active_only_input = QCheckBox()
        self.quarantine_active_only_input.setChecked(bool(quarantines.get("active_only", True)))
        self.quarantine_excluded_departments_input = QLineEdit(
            ", ".join(str(item) for item in quarantines.get("excluded_department_ids", []))
        )
        self.quarantine_departments_input = QTextEdit()
        self.quarantine_departments_input.setMinimumHeight(90)
        self.quarantine_departments_input.setPlaceholderText(
            "One per line, for example:\n1000055 = Technology\n1000058 = Power"
        )
        self.quarantine_departments_input.setPlainText(
            self.format_department_mappings(quarantines.get("department_mappings", {}))
        )

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
        form.addRow("Show quarantine leaderboard", self.quarantine_enabled_input)
        form.addRow("Quarantine department field", self.quarantine_field_input)
        form.addRow("Quarantine rows per page", self.quarantine_per_page_input)
        form.addRow("Quarantine max pages", self.quarantine_max_pages_input)
        form.addRow("Active quarantines only", self.quarantine_active_only_input)
        form.addRow("Ignored quarantine department IDs", self.quarantine_excluded_departments_input)
        form.addRow("Quarantine department names", self.quarantine_departments_input)
        rms_layout.addLayout(form)

        buttons = QHBoxLayout()
        save_btn = mark_primary(QPushButton("Save API Details Locally"))
        test_btn = QPushButton("Test Current RMS Connection")
        refresh_btn = QPushButton("Refresh Dashboard Now")
        save_btn.clicked.connect(self.save)
        test_btn.clicked.connect(self.test)
        refresh_btn.clicked.connect(self.refresh_now)
        buttons.addWidget(save_btn)
        buttons.addWidget(test_btn)
        buttons.addWidget(refresh_btn)
        buttons.addStretch(1)
        rms_layout.addLayout(buttons)

        note = QLabel(
            "API details and view IDs are stored only in manager_data/settings.json on the manager. "
            "That folder is ignored by Git and must not be committed."
        )
        note.setWordWrap(True)
        note.setObjectName("SectionSubtitle")
        rms_layout.addWidget(note)
        layout.addWidget(rms_panel)
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
            "quarantines": {
                "enabled": self.quarantine_enabled_input.isChecked(),
                "department_field": self.quarantine_field_input.text().strip()
                or "department_responsible_for_repair",
                "per_page": self.quarantine_per_page_input.value(),
                "max_pages": self.quarantine_max_pages_input.value(),
                "active_only": self.quarantine_active_only_input.isChecked(),
                "excluded_department_ids": self.parse_csv_ids(
                    self.quarantine_excluded_departments_input.text()
                ),
                "department_mappings": self.parse_department_mappings(
                    self.quarantine_departments_input.toPlainText()
                ),
            },
            "excluded_item_ids": self.parse_csv_ids(self.excluded_items_input.text()),
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
    @staticmethod
    def format_department_routes(routes):
        lines = []
        for department, targets in sorted((routes or {}).items(), key=lambda item: str(item[0]).lower()):
            if isinstance(targets, str):
                target_text = targets
            else:
                target_text = ", ".join(str(item) for item in (targets or []) if str(item).strip())
            if str(department).strip() and target_text.strip():
                lines.append(f"{department} = {target_text}")
        return "\n".join(lines)

    @staticmethod
    def parse_department_routes(text):
        routes = {}
        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                department, targets = line.split("=", 1)
            elif ":" in line:
                department, targets = line.split(":", 1)
            else:
                continue
            department = department.strip()
            target_values = [item.strip() for item in targets.split(",") if item.strip()]
            if department and target_values:
                routes[department] = target_values
        return routes

    @staticmethod
    def parse_csv(text):
        return [item.strip() for item in str(text or "").split(",") if item.strip()]

    def __init__(self, state):
        super().__init__()
        self.state = state
        layout = make_scroll_page(self)
        add_page_heading(
            layout,
            "Alerts",
            "Configure notification events, sounds, popup behaviour, and targeted test alerts for selected Pis.",
        )
        settings = self.state.get_settings(include_secret=True).get("alerts", {})
        event_types = settings.get("event_types", {})
        routing = settings.get("department_routing", {}) or {}

        rules_panel, rules_layout = make_panel(
            "Live Alert Rules",
            "Each alert type can independently show a popup, play a sound, or be tested against the selected Pi screens.",
        )
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
        rules_layout.addLayout(form)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
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
            test_button = mark_quiet(QPushButton("Test"))
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

        rules_layout.addLayout(grid)

        note = QLabel(
            "Alerts are sent to all currently registered Pis. "
            "Sound files are served from the manager's sounds folder and refreshed on each Pi before playback."
        )
        note.setWordWrap(True)
        note.setObjectName("SectionSubtitle")
        rules_layout.addWidget(note)

        buttons = QHBoxLayout()
        save_btn = mark_primary(QPushButton("Save Alert Settings"))
        refresh_btn = QPushButton("Apply and Refresh Now")
        save_btn.clicked.connect(self.save)
        refresh_btn.clicked.connect(self.apply_and_refresh)
        buttons.addWidget(save_btn)
        buttons.addWidget(refresh_btn)
        buttons.addStretch(1)
        rules_layout.addLayout(buttons)
        layout.addWidget(rules_panel)

        routing_panel, routing_layout = make_panel(
            "Job Change Department Routing",
            (
                "Route job-change alerts to department screens using the product prep department custom field. "
                "If a changed item has no department, it can still go to every screen."
            ),
        )
        routing_form = QFormLayout()
        self.department_routing_enabled = QCheckBox("Enable prep department routing for job-change alerts")
        self.department_routing_enabled.setChecked(bool(routing.get("enabled", True)))
        self.department_unknown_all = QCheckBox("Send no-department changes to all screens")
        self.department_unknown_all.setChecked(bool(routing.get("send_unknown_to_all", True)))
        self.department_field_names_input = QLineEdit(
            ", ".join(str(item) for item in routing.get("field_names", []) or [])
        )
        self.department_field_names_input.setPlaceholderText("prep_department, prep department, Prep Department")
        self.department_routes_input = QTextEdit()
        self.department_routes_input.setMinimumHeight(125)
        self.department_routes_input.setPlaceholderText(
            "One route per line, for example:\n"
            "Rigging = rigging\n"
            "Power = power\n"
            "Technology = technology\n"
            "TV Lights = tv lights"
        )
        self.department_routes_input.setPlainText(self.format_department_routes(routing.get("routes", {})))

        routing_form.addRow("", self.department_routing_enabled)
        routing_form.addRow("Custom field names", self.department_field_names_input)
        routing_form.addRow("Department routes", self.department_routes_input)
        routing_form.addRow("", self.department_unknown_all)
        routing_layout.addLayout(routing_form)

        routing_note = QLabel(
            "Left side is the Current RMS prep department value. Right side is one or more Pi name, ID, or screen "
            "match terms. Separate multiple targets with commas."
        )
        routing_note.setWordWrap(True)
        routing_note.setObjectName("SectionSubtitle")
        routing_layout.addWidget(routing_note)
        layout.addWidget(routing_panel)

        test_box, test_layout = make_panel(
            "Test Notifications",
            "Send a custom popup or category sound to only the checked Pi screens below.",
        )

        test_form = QFormLayout()
        self.test_title_input = QLineEdit("Test Notification")
        self.test_message_input = QTextEdit()
        self.test_message_input.setPlaceholderText("Type the popup text you want to show on the Pis.")
        self.test_message_input.setMinimumHeight(92)
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
        target_heading.setObjectName("SectionSubtitle")
        test_layout.addWidget(target_heading)

        self.test_device_table = QTableWidget(0, 4)
        self.test_device_table.setHorizontalHeaderLabels(["Send", "Name", "IP", "State"])
        self.test_device_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.test_device_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.test_device_table.setMinimumHeight(125)
        tune_table(self.test_device_table)
        test_layout.addWidget(self.test_device_table)

        test_buttons = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_none_btn = QPushButton("Select None")
        refresh_targets_btn = QPushButton("Refresh Pi Targets")
        send_test_btn = mark_primary(QPushButton("Send Test Notification To Selected Pis"))
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
            "department_routing": {
                "enabled": self.department_routing_enabled.isChecked(),
                "field_names": self.parse_csv(self.department_field_names_input.text()),
                "send_unknown_to_all": self.department_unknown_all.isChecked(),
                "routes": self.parse_department_routes(self.department_routes_input.toPlainText()),
            },
            "event_types": event_types,
        }

    def save(self):
        self.state.save_settings({"alerts": self.settings_payload()})
        QMessageBox.information(self, "Saved", "Alert settings saved on the manager.")

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


class ManagerInfoCard(QFrame):
    TONE_COLORS = {
        "good": "#2e7d32",
        "warn": "#f9a825",
        "bad": "#b71c1c",
        "info": "#1565c0",
        "muted": "#607d8b",
    }

    def __init__(self, title):
        super().__init__()
        self.setObjectName("ManagerInfoCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(5)

        self.title_label = QLabel(title.upper())
        self.title_label.setStyleSheet("color:#83c5d8; font-size:11px; font-weight:900; letter-spacing:1px;")
        self.value_label = QLabel("Loading")
        self.value_label.setStyleSheet("color:#f7fbff; font-size:19px; font-weight:900;")
        self.value_label.setWordWrap(True)
        self.detail_label = QLabel("")
        self.detail_label.setStyleSheet("color:#b7c7cf; font-size:12px; font-weight:650;")
        self.detail_label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label, 1)
        self.setMinimumHeight(94)
        self.setMaximumHeight(118)
        self.set_content("Loading", "", "muted")

    def set_content(self, value, detail="", tone="muted"):
        color = self.TONE_COLORS.get(tone, self.TONE_COLORS["muted"])
        self.setStyleSheet(
            f"QFrame#ManagerInfoCard {{ background:#141b20; border:1px solid #2b3a43; "
            f"border-left:7px solid {color}; border-radius:12px; }}"
        )
        self.value_label.setText(str(value or "Unknown"))
        self.detail_label.setText(str(detail or ""))


class ManagerPiTab(QWidget):
    command_finished = Signal(str)

    def __init__(self, state):
        super().__init__()
        self.setObjectName("ManagerPiTab")
        self.setStyleSheet(
            """
            QWidget#ManagerPiTab {
                background:#0e1216;
                color:#edf4f7;
            }
            QWidget#ManagerPiTab QLabel {
                color:#edf4f7;
            }
            QWidget#ManagerPiTab QPushButton {
                background:#22313a;
                color:#f5fbff;
                border:1px solid #3c515d;
                border-radius:8px;
                padding:6px 10px;
                font-weight:750;
            }
            QWidget#ManagerPiTab QPushButton:hover {
                background:#2d414d;
            }
            QWidget#ManagerPiTab QPushButton#PrimaryAction {
                background:#57d68d;
                color:#04130b;
                border-color:#57d68d;
            }
            QWidget#ManagerPiTab QPushButton#DangerAction {
                background:#793238;
                border-color:#a84a52;
            }
            QWidget#ManagerPiTab QLineEdit,
            QWidget#ManagerPiTab QTextEdit {
                background:#0b0f13;
                color:#f5fbff;
                border:1px solid #3c515d;
                border-radius:7px;
                padding:5px;
                selection-background-color:#57d68d;
                selection-color:#04130b;
            }
            """
        )
        self.state = state
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer_layout.addWidget(self.scroll_area)

        content = QWidget()
        content.setObjectName("ManagerPiContent")
        self.scroll_area.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 14)
        layout.setSpacing(10)

        heading = QLabel("Manager Pi Control")
        heading.setStyleSheet("font-size: 21px; font-weight: 900;")
        layout.addWidget(heading)

        intro = QLabel(
            "These controls affect the Manager Pi backend, not the individual dashboard screen Pis. "
            "Use this page to update or restart the always-on Manager Pi."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#a9bac3; font-size:12px;")
        layout.addWidget(intro)

        status_grid = QGridLayout()
        status_grid.setSpacing(10)
        status_grid.setColumnStretch(0, 1)
        status_grid.setColumnStretch(1, 1)
        status_grid.setColumnStretch(2, 1)
        self.connection_card = ManagerInfoCard("Connection")
        self.software_card = ManagerInfoCard("Software")
        self.services_card = ManagerInfoCard("Services")
        self.security_card = ManagerInfoCard("Security")
        self.manager_update_card = ManagerInfoCard("Last Manager Update")
        self.version_card = ManagerInfoCard("Version")
        status_grid.addWidget(self.connection_card, 0, 0)
        status_grid.addWidget(self.software_card, 0, 1)
        status_grid.addWidget(self.services_card, 0, 2)
        status_grid.addWidget(self.security_card, 1, 0)
        status_grid.addWidget(self.manager_update_card, 1, 1)
        status_grid.addWidget(self.version_card, 1, 2)
        layout.addLayout(status_grid)

        actions_frame, actions_layout = self.make_section("Actions", "Update, restart, or reboot the Manager Pi.")
        primary_buttons = QHBoxLayout()
        check_btn = QPushButton("Check For Updates")
        update_all_btn = QPushButton("Update Manager + All Pis")
        update_all_btn.setObjectName("PrimaryAction")
        update_btn = QPushButton("Update Manager Pi")
        primary_buttons.addWidget(check_btn)
        primary_buttons.addWidget(update_all_btn)
        primary_buttons.addWidget(update_btn)
        primary_buttons.addStretch(1)
        actions_layout.addLayout(primary_buttons)

        service_buttons = QHBoxLayout()
        restart_backend_btn = QPushButton("Restart Backend")
        restart_display_btn = QPushButton("Restart Status Display")
        reboot_btn = QPushButton("Reboot Manager Pi")
        reboot_btn.setObjectName("DangerAction")

        check_btn.clicked.connect(lambda: self.run_command("check_updates"))
        update_all_btn.clicked.connect(lambda: self.run_command("update_all", confirm=True))
        update_btn.clicked.connect(lambda: self.run_command("update", confirm=True))
        restart_backend_btn.clicked.connect(lambda: self.run_command("restart_backend", confirm=True))
        restart_display_btn.clicked.connect(lambda: self.run_command("restart_display", confirm=True))
        reboot_btn.clicked.connect(lambda: self.run_command("reboot", confirm=True))

        service_buttons.addWidget(restart_backend_btn)
        service_buttons.addWidget(restart_display_btn)
        service_buttons.addWidget(reboot_btn)
        service_buttons.addStretch(1)
        actions_layout.addLayout(service_buttons)

        self.command_status = QLabel("Ready.")
        self.command_status.setWordWrap(True)
        self.command_status.setStyleSheet(
            "background:#101820; border:1px solid #2b3a43; border-radius:8px; padding:7px; "
            "color:#c8d6dd; font-weight:800;"
        )
        actions_layout.addWidget(self.command_status)
        layout.addWidget(actions_frame)

        log_frame, log_layout = self.make_section("Manager Update Log", "Latest output from the Manager Pi updater.")
        self.manager_update_log = QTextEdit()
        self.manager_update_log.setReadOnly(True)
        self.manager_update_log.setMinimumHeight(115)
        self.manager_update_log.setPlaceholderText("Manager Pi update log will appear here after an update starts.")
        log_layout.addWidget(self.manager_update_log)
        layout.addWidget(log_frame, 1)

        password_frame, password_layout = self.make_section(
            "Change Manager Pi Password",
            "Used by the PC app when connecting to the Manager Pi backend.",
        )
        password_box = QGridLayout()

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
        password_layout.addLayout(password_box)
        layout.addWidget(password_frame)

        self.command_finished.connect(self.on_command_finished)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(5000)
        self.refresh()

    def make_section(self, title, subtitle=""):
        frame = QFrame()
        frame.setObjectName("ManagerSection")
        frame.setStyleSheet(
            "QFrame#ManagerSection { background:#141b20; border:1px solid #2b3a43; border-radius:12px; }"
        )
        section_layout = QVBoxLayout(frame)
        section_layout.setContentsMargins(12, 10, 12, 10)
        section_layout.setSpacing(7)

        title_label = QLabel(title)
        title_label.setStyleSheet("color:#f7fbff; font-size:15px; font-weight:900;")
        section_layout.addWidget(title_label)
        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setWordWrap(True)
            subtitle_label.setStyleSheet("color:#9fb0b8;")
            section_layout.addWidget(subtitle_label)
        return frame, section_layout

    def refresh(self):
        try:
            status = self.state.get_manager_status()
        except Exception as error:
            self.connection_card.set_content("Offline", f"Could not read Manager Pi status: {error}", "bad")
            self.software_card.set_content("Unknown", "No update status available.", "muted")
            self.services_card.set_content("Unknown", "No service status available.", "muted")
            self.security_card.set_content("Unknown", "No security status available.", "muted")
            self.manager_update_card.set_content("Unknown", "No update status available.", "muted")
            self.version_card.set_content("Unknown", "No version status available.", "muted")
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
        self.connection_card.set_content(
            "Connected" if status.get("is_manager_pi") else "Unavailable",
            role_text,
            "good" if status.get("is_manager_pi") else "warn",
        )
        self.software_card.set_content(
            "Check Failed" if error else "Update Available" if update_status.get("manager_update_available") else "Current",
            f"GitHub v{latest} | Manager v{local}\nChecked: {checked_at}.",
            "bad" if error else "warn" if update_status.get("manager_update_available") else "good",
        )

        backend_service = str(status.get("backend_service", "unknown"))
        display_service = str(status.get("display_service", "unknown"))
        update_service = str(status.get("update_service", "unknown"))
        service_problem = backend_service.lower() in {"failed", "inactive"} or display_service.lower() in {
            "failed",
            "inactive",
        }
        self.services_card.set_content(
            "Check" if service_problem else "Healthy",
            f"Backend {backend_service} | Display {display_service}\nUpdater {update_service} (manual service)",
            "bad" if service_problem else "good",
        )

        security = status.get("security", {}) or {}
        if security.get("legacy_code_active"):
            security_value = "Change Password"
            security_detail = "Old legacy code is active. Change it to a private password below."
            security_tone = "warn"
        elif security.get("password_set"):
            updated = str(security.get("updated_at") or "").strip()
            security_value = "Protected"
            security_detail = f"Password protected{f' since {updated}' if updated else ''}."
            security_tone = "good"
        else:
            security_value = "Setup Needed"
            security_detail = "Initial password has not been confirmed yet."
            security_tone = "warn"
        self.security_card.set_content(security_value, security_detail, security_tone)

        manager_update = status.get("manager_update_status", {}) or {}
        if manager_update:
            progress = manager_update.get("progress", 0)
            state = str(manager_update.get("state", "")).strip()
            title = str(manager_update.get("title", "")).strip()
            detail = str(manager_update.get("detail", "")).strip()
            updated_at = str(manager_update.get("updated_at", "")).strip()
            self.manager_update_card.set_content(
                f"{progress}% {state}".strip(),
                f"{title}\n{detail}\n{updated_at}".strip(),
                "bad" if state.lower() == "failed" else "warn" if state.lower() in {"running", "updating"} else "good",
            )
        else:
            self.manager_update_card.set_content("No Update Run", "No Manager Pi update log yet.", "muted")

        self.version_card.set_content(
            f"v{local}",
            f"GitHub latest: v{latest}",
            "warn" if update_status.get("manager_update_available") else "good",
        )

        log_text = str(status.get("manager_update_log") or "").strip()
        if log_text and self.manager_update_log.toPlainText() != log_text:
            self.manager_update_log.setPlainText(log_text)
            self.manager_update_log.verticalScrollBar().setValue(self.manager_update_log.verticalScrollBar().maximum())

    def run_command(self, action, confirm=False):
        confirm_messages = {
            "update_all": (
                "Update every registered dashboard Pi and the Manager Pi from GitHub?\n\n"
                "Dashboard Pi updates will be queued first. The Manager Pi update will start shortly after "
                "so the screens have time to collect their update command."
            ),
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
    command_finished = Signal(str)

    COLUMNS = ["ID", "Name", "IP", "Screen", "Scale", "Version", "Update", "State", "Activity", "Last Seen"]
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
        self.setObjectName("WarehousePage")
        self.state = state
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 14)
        layout.setSpacing(10)
        add_page_heading(
            layout,
            "Pi Screens",
            "Monitor every registered dashboard Pi and send screen, update, restart, reboot, rename, and display-size commands.",
        )

        self.update_status = make_status_label("Checking GitHub update status...")
        layout.addWidget(self.update_status)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.MultiSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setMinimumHeight(260)
        tune_table(self.table)
        layout.addWidget(self.table)

        controls_panel, controls_layout = make_panel(
            "Selected Pi Controls",
            "Select one or more rows above, then use these buttons to change screens or queue actions.",
        )
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
        screen_buttons.addStretch(1)
        controls_layout.addLayout(screen_buttons)

        command_buttons = QHBoxLayout()
        rename_btn = QPushButton("Rename Pi")
        display_size_btn = QPushButton("Set Display Size")
        restart_btn = QPushButton("Restart Display App")
        update_btn = QPushButton("Update Pi From GitHub")
        update_all_btn = mark_primary(QPushButton("Update All Pis + Manager"))
        check_updates_btn = QPushButton("Check GitHub Updates")
        reboot_btn = mark_danger(QPushButton("Reboot Pi"))
        remove_btn = mark_danger(QPushButton("Remove Selected"))
        refresh_btn = QPushButton("Refresh List")
        rename_btn.clicked.connect(self.rename_selected_pi)
        display_size_btn.clicked.connect(self.set_display_size_selected)
        restart_btn.clicked.connect(lambda: self.send_action("restart"))
        update_btn.clicked.connect(lambda: self.send_action("update"))
        update_all_btn.clicked.connect(self.update_all)
        check_updates_btn.clicked.connect(self.check_updates_now)
        reboot_btn.clicked.connect(lambda: self.send_action("reboot"))
        remove_btn.clicked.connect(self.remove_selected_pis)
        refresh_btn.clicked.connect(self.refresh)
        command_buttons.addWidget(rename_btn)
        command_buttons.addWidget(display_size_btn)
        command_buttons.addWidget(restart_btn)
        command_buttons.addWidget(update_btn)
        command_buttons.addWidget(update_all_btn)
        command_buttons.addStretch(1)
        controls_layout.addLayout(command_buttons)

        service_buttons = QHBoxLayout()
        service_buttons.addWidget(check_updates_btn)
        service_buttons.addWidget(refresh_btn)
        service_buttons.addStretch(1)
        service_buttons.addWidget(reboot_btn)
        service_buttons.addWidget(remove_btn)
        controls_layout.addLayout(service_buttons)
        layout.addWidget(controls_panel)

        self.status = make_status_label("Waiting for Pi screens to register...")
        layout.addWidget(self.status)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(3000)
        self.command_finished.connect(self.on_command_finished)
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
            scale_item = self.table.item(row, 4)
            if not device_id_item:
                continue
            devices.append(
                {
                    "id": device_id_item.text(),
                    "name": device_name_item.text() if device_name_item else "",
                    "display_scale": scale_item.text().rstrip("%") if scale_item else "",
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
                f"{device.get('display_scale', 100)}%",
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

    def update_all(self):
        choice = QMessageBox.question(
            self,
            "Update Manager And All Pis?",
            (
                "Update every registered dashboard Pi and the Manager Pi from GitHub?\n\n"
                "Dashboard Pi updates will be queued first. The Manager Pi update will start shortly after "
                "so the screens have time to collect their update command."
            ),
        )
        if choice != QMessageBox.Yes:
            return

        self.status.setText("Starting update all: queueing dashboard Pi updates, then Manager Pi update...")

        def worker():
            try:
                result = self.state.run_manager_command("update_all")
                message = str(result.get("message") or "Update all started.")
            except Exception as error:
                message = f"Update all failed: {error}"
            self.command_finished.emit(message)

        Thread(target=worker, daemon=True).start()

    def on_command_finished(self, message):
        self.status.setText(message)
        self.refresh()

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

    def set_display_size_selected(self):
        devices = self.selected_devices()
        if not devices:
            QMessageBox.warning(self, "No Pi Selected", "Select one or more Pi screens first.")
            return

        default_scale = 100
        if len(devices) == 1:
            try:
                default_scale = int(float(devices[0].get("display_scale") or 100))
            except Exception:
                default_scale = 100

        scale, accepted = QInputDialog.getInt(
            self,
            "Set Display Size",
            "Display size percent:\n100 = normal, 125 = larger, 150 = very large",
            default_scale,
            75,
            200,
            5,
        )
        if not accepted:
            return

        device_ids = [device["id"] for device in devices]
        self.state.queue_command(device_ids, "set_display_scale", display_scale=int(scale))
        self.status.setText(f"Queued {scale}% display size for {len(device_ids)} Pi screen(s).")

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
        self.setObjectName("WarehousePage")
        self.state = state
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 14)
        layout.setSpacing(10)
        add_page_heading(
            layout,
            "Console",
            "Live manager activity, diagnostics, and behind-the-scenes event history.",
        )

        controls_panel, controls_layout = make_toolbar_panel()
        controls = QHBoxLayout()
        self.category_filter = QComboBox()
        self.category_filter.addItems(["All", "Current RMS", "Pis", "Audio", "Notifications", "Updates", "Commands", "Settings", "Manager"])
        self.level_filter = QComboBox()
        self.level_filter.addItems(["All", "info", "warning", "error"])
        refresh_btn = QPushButton("Refresh")
        clear_btn = mark_danger(QPushButton("Clear"))
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
        controls_layout.addLayout(controls)
        layout.addWidget(controls_panel)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.MultiSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        tune_table(self.table)
        layout.addWidget(self.table)

        self.status = make_status_label()
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
        self.resize(1280, 820)
        self.setStyleSheet(APP_STYLESHEET)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
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

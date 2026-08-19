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
    QColorDialog,
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

UNKNOWN_DEPARTMENT_ROUTE = "__unknown__"
PREP_DEPARTMENT_ROUTES = [
    ("1000083", "Power"),
    ("1000012", "Rigging"),
    ("1000010", "Technology"),
    ("1000011", "TV Lights"),
    (UNKNOWN_DEPARTMENT_ROUTE, "No Prep Department"),
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
    background: #eef3f7;
}
QWidget {
    color: #17212b;
    font-family: "Segoe UI", "Aptos", "Verdana";
    font-size: 11px;
}
QWidget#WarehousePage {
    background: #eef3f7;
}
QScrollArea {
    background: #eef3f7;
    border: 0;
}
QScrollBar:vertical {
    background: #dbe4ec;
    width: 11px;
    margin: 2px;
    border-radius: 6px;
}
QScrollBar::handle:vertical {
    background: #8fa1b2;
    border-radius: 6px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: #315b7c;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}
QTabWidget::pane {
    border-top: 1px solid #c8d4df;
    background: #eef3f7;
}
QTabBar::tab {
    background: #dfe8f0;
    color: #314255;
    border: 1px solid #c2ceda;
    border-bottom-color: #c8d4df;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 8px 15px;
    margin-right: 2px;
    font-weight: 750;
}
QTabBar::tab:selected {
    background: #244e73;
    color: #ffffff;
    border-color: #244e73;
}
QTabBar::tab:hover:!selected {
    background: #edf3f8;
    color: #17212b;
}
QLabel {
    color: #17212b;
    background: transparent;
}
QLabel#PageTitle {
    font-size: 20px;
    font-weight: 900;
    color: #102538;
}
QLabel#PageIntro {
    color: #506579;
    font-size: 12px;
    font-weight: 600;
}
QLabel#SectionTitle {
    color: #17212b;
    font-size: 15px;
    font-weight: 900;
}
QLabel#SectionSubtitle {
    color: #5c7082;
    font-weight: 600;
}
QLabel#StatusStrip {
    background: #e6edf4;
    border: 1px solid #c9d5df;
    border-radius: 8px;
    color: #26394b;
    font-weight: 800;
    padding: 7px;
}
QFrame#WarehousePanel,
QFrame#ManagerSection {
    background: #ffffff;
    border: 1px solid #d1dce6;
    border-radius: 12px;
}
QFrame#ToolbarPanel {
    background: #ffffff;
    border: 1px solid #d1dce6;
    border-radius: 12px;
}
QLineEdit,
QTextEdit,
QPlainTextEdit,
QSpinBox,
QComboBox {
    background: #fbfdff;
    color: #17212b;
    border: 1px solid #b9c8d6;
    border-radius: 7px;
    padding: 5px;
    selection-background-color: #244e73;
    selection-color: #ffffff;
}
QLineEdit:focus,
QTextEdit:focus,
QPlainTextEdit:focus,
QSpinBox:focus,
QComboBox:focus {
    border-color: #244e73;
}
QLineEdit:disabled,
QTextEdit:disabled,
QSpinBox:disabled,
QComboBox:disabled {
    color: #8292a2;
    border-color: #ccd6df;
    background: #eef2f6;
}
QTextEdit {
    line-height: 1.35em;
}
QComboBox::drop-down {
    border-left: 1px solid #c8d4df;
    width: 24px;
}
QPushButton {
    background: #e8eef4;
    color: #17212b;
    border: 1px solid #b8c7d4;
    border-radius: 8px;
    padding: 6px 10px;
    font-weight: 800;
}
QPushButton:hover {
    background: #f7fbff;
    border-color: #7f98ad;
}
QPushButton:pressed {
    background: #dbe5ee;
}
QPushButton#PrimaryAction {
    background: #1c6b57;
    color: #ffffff;
    border-color: #1c6b57;
}
QPushButton#PrimaryAction:hover {
    background: #238267;
}
QPushButton#DangerAction {
    background: #b42318;
    color: #ffffff;
    border-color: #b42318;
}
QPushButton#DangerAction:hover {
    background: #d13a2f;
}
QPushButton#QuietAction {
    background: #eef3f7;
    color: #244e73;
}
QCheckBox {
    background: transparent;
    color: #17212b;
    spacing: 6px;
    font-weight: 650;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 5px;
    border: 1px solid #8ea0b1;
    background: #ffffff;
}
QCheckBox::indicator:checked {
    background: #1c6b57;
    border-color: #1c6b57;
}
QTableWidget {
    background: #ffffff;
    alternate-background-color: #f5f8fb;
    color: #17212b;
    gridline-color: #d5dee7;
    border: 1px solid #c9d5df;
    border-radius: 10px;
    selection-background-color: #d8e9f7;
    selection-color: #17212b;
}
QTableWidget::item {
    padding: 4px;
    border-bottom: 1px solid #e3e9ef;
}
QTableWidget::item:selected {
    background: #d8e9f7;
}
QHeaderView::section {
    background: #edf3f8;
    color: #315b7c;
    border: 0;
    border-right: 1px solid #d1dce6;
    border-bottom: 1px solid #d1dce6;
    padding: 6px;
    font-weight: 900;
}
QMessageBox {
    background: #ffffff;
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


def safe_emit(signal, payload):
    try:
        signal.emit(payload)
    except RuntimeError:
        pass


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
            "Setup",
            "Network settings and live one-command installers for dashboard screens and Manager Pi deployments.",
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
            "Data Source",
            "Current RMS API connection, job view IDs, excluded items, and quarantine leaderboard settings.",
        )

        rms_panel, rms_layout = make_panel(
            "API Connection",
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
            "unreturned": QLineEdit(str(views.get("unreturned", ""))),
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
        rms_layout.addLayout(form)
        layout.addWidget(rms_panel)

        views_panel, views_layout = make_panel(
            "Dashboard Views",
            "Current RMS saved views used for Today, Tomorrow, Prep, Outstanding, and Unreturned tabs.",
        )
        views_form = QFormLayout()
        views_form.addRow("Today out view", self.view_inputs["today_out"])
        views_form.addRow("Today in view", self.view_inputs["today_in"])
        views_form.addRow("Tomorrow out view", self.view_inputs["tomorrow_out"])
        views_form.addRow("Tomorrow in view", self.view_inputs["tomorrow_in"])
        views_form.addRow("Prep / next 7 days view", self.view_inputs["prep"])
        views_form.addRow("Outstanding view", self.view_inputs["outstanding"])
        views_form.addRow("Unreturned jobs view", self.view_inputs["unreturned"])
        views_form.addRow("Prep / alert excluded item IDs", self.excluded_items_input)
        views_layout.addLayout(views_form)
        layout.addWidget(views_panel)

        quarantine_panel, quarantine_layout = make_panel(
            "Quarantine Leaderboard",
            "Department mapping and paging for the quarantine tiles shown on the dashboards.",
        )
        quarantine_form = QFormLayout()
        quarantine_form.addRow("Show quarantine leaderboard", self.quarantine_enabled_input)
        quarantine_form.addRow("Quarantine department field", self.quarantine_field_input)
        quarantine_form.addRow("Quarantine rows per page", self.quarantine_per_page_input)
        quarantine_form.addRow("Quarantine max pages", self.quarantine_max_pages_input)
        quarantine_form.addRow("Active quarantines only", self.quarantine_active_only_input)
        quarantine_form.addRow("Ignored quarantine department IDs", self.quarantine_excluded_departments_input)
        quarantine_form.addRow("Quarantine department names", self.quarantine_departments_input)
        quarantine_layout.addLayout(quarantine_form)
        layout.addWidget(quarantine_panel)

        actions_panel, actions_layout = make_panel(
            "Data Actions",
            "Save settings, test the API credentials, or force the manager to refresh dashboard data now.",
        )
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
        actions_layout.addLayout(buttons)

        note = QLabel(
            "API details and view IDs are stored only in manager_data/settings.json on the manager. "
            "That folder is ignored by Git and must not be committed."
        )
        note.setWordWrap(True)
        note.setObjectName("SectionSubtitle")
        actions_layout.addWidget(note)
        layout.addWidget(actions_panel)
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
    DELIVERY_MODES = [
        ("popup_sound", "Popup + sound"),
        ("popup_only", "Popup only (silent)"),
        ("sound_only", "Sound only"),
        ("log_only", "Log/email only"),
    ]

    @classmethod
    def populate_delivery_combo(cls, combo, config=None, default_mode="popup_sound"):
        for key, label in cls.DELIVERY_MODES:
            combo.addItem(label, key)
        mode = cls.delivery_mode_from_config(config or {}, default_mode=default_mode)
        index = combo.findData(mode)
        combo.setCurrentIndex(index if index >= 0 else 0)

    @staticmethod
    def delivery_mode_from_config(config, default_mode="popup_sound"):
        if "delivery_mode" in config:
            mode = str(config.get("delivery_mode") or "").strip()
            if mode in {"popup_sound", "popup_only", "sound_only", "log_only"}:
                return mode
        show_popup = bool(config.get("show_popup", default_mode in {"popup_sound", "popup_only"}))
        play_sound = bool(config.get("play_sound", default_mode in {"popup_sound", "sound_only"}))
        if show_popup and play_sound:
            return "popup_sound"
        if show_popup:
            return "popup_only"
        if play_sound:
            return "sound_only"
        return "log_only"

    @staticmethod
    def delivery_flags(mode):
        clean_mode = str(mode or "popup_sound")
        return {
            "show_popup": clean_mode in {"popup_sound", "popup_only"},
            "play_sound": clean_mode in {"popup_sound", "sound_only"},
            "delivery_mode": clean_mode,
        }

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

    @staticmethod
    def parse_recipients(text):
        values = []
        for chunk in str(text or "").replace(";", "\n").replace(",", "\n").splitlines():
            item = chunk.strip()
            if item:
                values.append(item)
        return values

    @staticmethod
    def normalise_route_value(value):
        return "".join(character for character in str(value or "").strip().lower() if character.isalnum())

    @staticmethod
    def device_label(device):
        name = str(device.get("name") or device.get("id") or "Pi").strip()
        ip = str(device.get("ip") or "").strip()
        return f"{name}\n{ip}" if ip else name

    @classmethod
    def route_targets_match_device(cls, targets, device):
        if isinstance(targets, str):
            targets = [item.strip() for item in targets.split(",") if item.strip()]
        if not isinstance(targets, list):
            targets = []
        target_terms = {cls.normalise_route_value(item) for item in targets if cls.normalise_route_value(item)}
        if not target_terms:
            return False

        exact_terms = [
            cls.normalise_route_value(value)
            for value in (device.get("id", ""),)
            if str(value).strip()
        ]
        fuzzy_terms = [
            cls.normalise_route_value(value)
            for value in (device.get("name", ""), device.get("screen", ""))
            if str(value).strip()
        ]
        if any(target == term for target in target_terms for term in exact_terms):
            return True
        return any(
            target == term or target in term or term in target
            for target in target_terms
            for term in fuzzy_terms
        )

    def make_route_table(self, rows, route_map, default_checked=False):
        devices = list(getattr(self, "routing_devices", []) or [])
        table = QTableWidget(len(rows), len(devices) + 1)
        table.setHorizontalHeaderLabels(["Alert / Route", *[self.device_label(device) for device in devices]])
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setMinimumHeight(max(150, 42 + (len(rows) * 34)))
        tune_table(table)

        for row_index, (route_key, label) in enumerate(rows):
            label_item = QTableWidgetItem(str(label))
            label_item.setData(Qt.UserRole, route_key)
            label_item.setFlags(label_item.flags() & ~Qt.ItemIsEditable)
            table.setItem(row_index, 0, label_item)

            route_defined = isinstance(route_map, dict) and route_key in route_map
            route_targets = route_map.get(route_key, []) if route_defined else []
            for column, device in enumerate(devices, start=1):
                checked = (
                    self.route_targets_match_device(route_targets, device)
                    if route_defined
                    else bool(default_checked(route_key, device) if callable(default_checked) else default_checked)
                )
                item = QTableWidgetItem("")
                item.setFlags((item.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable)
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
                item.setData(Qt.UserRole, str(device.get("id", "")).strip())
                table.setItem(row_index, column, item)

        table.resizeColumnsToContents()
        return table

    def route_table_payload(self, table):
        if table.columnCount() <= 1:
            return None
        routes = {}
        for row in range(table.rowCount()):
            label_item = table.item(row, 0)
            route_key = str(label_item.data(Qt.UserRole) if label_item else "").strip()
            if not route_key:
                continue
            selected = []
            for column in range(1, table.columnCount()):
                item = table.item(row, column)
                device_id = str(item.data(Qt.UserRole) if item else "").strip()
                if device_id and item.checkState() == Qt.Checked:
                    selected.append(device_id)
            routes[route_key] = selected
        return routes

    def set_route_table_all(self, table, checked):
        for row in range(table.rowCount()):
            for column in range(1, table.columnCount()):
                item = table.item(row, column)
                if item:
                    item.setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def __init__(self, state):
        super().__init__()
        self.state = state
        layout = make_scroll_page(self)
        add_page_heading(
            layout,
            "Notifications",
            "Choose how each alert is delivered, where it is routed, which sounds it uses, and who gets email copies.",
        )
        settings = self.state.get_settings(include_secret=True).get("alerts", {})
        event_types = settings.get("event_types", {})
        event_routes = settings.get("event_routes", {}) if isinstance(settings.get("event_routes", {}), dict) else {}
        routing = settings.get("department_routing", {}) or {}
        email = settings.get("email", {}) or {}
        self.routing_devices = self.state.list_devices()
        self.original_event_routes = dict(event_routes)
        self.original_department_routes = dict(routing.get("routes", {}) if isinstance(routing.get("routes", {}), dict) else {})
        self.original_unknown_all = bool(routing.get("send_unknown_to_all", True))

        rules_panel, rules_layout = make_panel(
            "Live Alert Rules",
            "Set the delivery mode for each alert type. Use Popup only (silent) when staff need to confirm the message without an audio cue.",
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
        grid.addWidget(QLabel("Delivery"), 0, 2)
        grid.addWidget(QLabel("Email"), 0, 3)
        grid.addWidget(QLabel("Sound File"), 0, 4)
        grid.addWidget(QLabel("Test"), 0, 5)

        self.event_inputs = {}
        for row, (event_key, label) in enumerate(ALERT_LABELS, start=1):
            config = event_types.get(event_key, {})
            enabled = QCheckBox()
            enabled.setChecked(bool(config.get("enabled", True)))
            delivery = QComboBox()
            self.populate_delivery_combo(delivery, config)
            send_email = QCheckBox()
            send_email.setChecked(bool(config.get("send_email", False)))
            sound_name = QLineEdit(str(config.get("sound", "")))
            test_button = mark_quiet(QPushButton("Test"))
            test_button.clicked.connect(
                lambda _checked=False, key=event_key, text=label: self.send_category_test_notification(key, text)
            )

            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(enabled, row, 1, alignment=Qt.AlignCenter)
            grid.addWidget(delivery, row, 2)
            grid.addWidget(send_email, row, 3, alignment=Qt.AlignCenter)
            grid.addWidget(sound_name, row, 4)
            grid.addWidget(test_button, row, 5)

            self.event_inputs[event_key] = {
                "enabled": enabled,
                "delivery": delivery,
                "send_email": send_email,
                "sound": sound_name,
                "test": test_button,
            }

        rules_layout.addLayout(grid)

        note = QLabel(
            "Use the routing sections below to choose exactly which registered Pis receive each live alert. "
            "Sound files are only used when the delivery mode includes sound."
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

        email_panel, email_layout = make_panel(
            "SMTP Email Alerts",
            "Email credentials are stored only on this manager. Tick Email beside any alert type above to send it by SMTP.",
        )
        email_form = QFormLayout()
        self.email_enabled = QCheckBox("Enable SMTP email alerts")
        self.email_enabled.setChecked(bool(email.get("enabled", False)))
        self.smtp_host_input = QLineEdit(str(email.get("smtp_host", "")))
        self.smtp_host_input.setPlaceholderText("smtp.office365.com")
        self.smtp_port_input = QSpinBox()
        self.smtp_port_input.setRange(1, 65535)
        try:
            smtp_port = int(email.get("smtp_port", 587) or 587)
        except Exception:
            smtp_port = 587
        self.smtp_port_input.setValue(smtp_port)
        self.smtp_security_input = QComboBox()
        self.smtp_security_input.addItems(["starttls", "ssl", "none"])
        security_value = str(email.get("smtp_security", "starttls") or "starttls").lower()
        if security_value in {"ssl/tls", "tls"}:
            security_value = "ssl"
        index = self.smtp_security_input.findText(security_value)
        self.smtp_security_input.setCurrentIndex(index if index >= 0 else 0)
        self.smtp_username_input = QLineEdit(str(email.get("username", "")))
        self.smtp_password_input = QLineEdit(str(email.get("password", "")))
        self.smtp_password_input.setEchoMode(QLineEdit.Password)
        self.smtp_from_address_input = QLineEdit(str(email.get("from_address", "")))
        self.smtp_from_name_input = QLineEdit(str(email.get("from_name", "Warehouse Dashboard")))
        self.email_recipients_input = QTextEdit()
        recipients = email.get("recipients", [])
        if isinstance(recipients, str):
            recipients_text = recipients
        else:
            recipients_text = "\n".join(str(item) for item in recipients or [])
        self.email_recipients_input.setPlainText(recipients_text)
        self.email_recipients_input.setPlaceholderText("one@email.com\nanother@email.com")
        self.email_recipients_input.setMinimumHeight(72)
        self.email_subject_template_input = QLineEdit(str(email.get("subject_template", "Warehouse alert: {alert_title}")))
        self.email_body_template_input = QTextEdit()
        self.email_body_template_input.setPlainText(
            str(
                email.get(
                    "body_template",
                    "{alert_title}\n\n{alert_details}\n\nJob: {job_name}\nJob Number: {job_number}\nClient: {client}\nOwner: {owner}\nReturned At: {returned_at}\n",
                )
            )
        )
        self.email_body_template_input.setMinimumHeight(110)

        email_form.addRow("", self.email_enabled)
        email_form.addRow("SMTP host", self.smtp_host_input)
        email_form.addRow("SMTP port", self.smtp_port_input)
        email_form.addRow("Security", self.smtp_security_input)
        email_form.addRow("Username", self.smtp_username_input)
        email_form.addRow("Password", self.smtp_password_input)
        email_form.addRow("From address", self.smtp_from_address_input)
        email_form.addRow("From name", self.smtp_from_name_input)
        email_form.addRow("Recipients", self.email_recipients_input)
        email_form.addRow("Subject template", self.email_subject_template_input)
        email_form.addRow("Body template", self.email_body_template_input)
        email_layout.addLayout(email_form)

        email_help = QLabel(
            "Template fields: {alert_title}, {alert_details}, {job_name}, {job_number}, {client}, {owner}, {returned_at}."
        )
        email_help.setWordWrap(True)
        email_help.setObjectName("SectionSubtitle")
        email_layout.addWidget(email_help)
        email_buttons = QHBoxLayout()
        test_email_btn = mark_primary(QPushButton("Save and Send Test Email"))
        test_email_btn.clicked.connect(self.test_email)
        email_buttons.addWidget(test_email_btn)
        email_buttons.addStretch(1)
        email_layout.addLayout(email_buttons)
        layout.addWidget(email_panel)

        delivery_panel, delivery_layout = make_panel(
            "Alert Delivery",
            "Tick the Pi screens that should receive each alert type. Tick multiple screens to send the same alert to more than one place.",
        )
        if not self.routing_devices:
            no_devices = QLabel("No Pi screens are registered yet. Once screens appear, reopen this tab to build the routing grid.")
            no_devices.setWordWrap(True)
            no_devices.setObjectName("SectionSubtitle")
            delivery_layout.addWidget(no_devices)
        self.event_route_table = self.make_route_table(
            ALERT_LABELS,
            event_routes,
            default_checked=True,
        )
        delivery_layout.addWidget(self.event_route_table)
        delivery_buttons = QHBoxLayout()
        delivery_all_btn = QPushButton("Tick All")
        delivery_none_btn = QPushButton("Clear All")
        delivery_all_btn.clicked.connect(lambda: self.set_route_table_all(self.event_route_table, True))
        delivery_none_btn.clicked.connect(lambda: self.set_route_table_all(self.event_route_table, False))
        delivery_buttons.addWidget(delivery_all_btn)
        delivery_buttons.addWidget(delivery_none_btn)
        delivery_buttons.addStretch(1)
        delivery_layout.addLayout(delivery_buttons)
        delivery_note = QLabel(
            "This is the first routing filter. Department job-change routes below can narrow those alerts further."
        )
        delivery_note.setWordWrap(True)
        delivery_note.setObjectName("SectionSubtitle")
        delivery_layout.addWidget(delivery_note)
        layout.addWidget(delivery_panel)

        routing_panel, routing_layout = make_panel(
            "Job Change Department Routing",
            (
                "Tick which Pi screens receive job-change alerts for each Current RMS prep department. "
                "This replaces the old manual route list."
            ),
        )
        routing_form = QFormLayout()
        self.department_routing_enabled = QCheckBox("Enable prep department routing for job-change alerts")
        self.department_routing_enabled.setChecked(bool(routing.get("enabled", True)))
        self.department_field_names_input = QLineEdit(
            ", ".join(str(item) for item in routing.get("field_names", []) or [])
        )
        self.department_field_names_input.setPlaceholderText("prep_department")

        routing_form.addRow("", self.department_routing_enabled)
        routing_form.addRow("Custom field names", self.department_field_names_input)
        routing_layout.addLayout(routing_form)

        department_routes = self.original_department_routes
        unknown_default = self.original_unknown_all
        self.department_route_table = self.make_route_table(
            PREP_DEPARTMENT_ROUTES,
            department_routes,
            default_checked=lambda route_key, _device: route_key == UNKNOWN_DEPARTMENT_ROUTE and unknown_default,
        )
        routing_layout.addWidget(self.department_route_table)
        department_buttons = QHBoxLayout()
        department_all_btn = QPushButton("Tick All")
        department_none_btn = QPushButton("Clear All")
        department_all_btn.clicked.connect(lambda: self.set_route_table_all(self.department_route_table, True))
        department_none_btn.clicked.connect(lambda: self.set_route_table_all(self.department_route_table, False))
        department_buttons.addWidget(department_all_btn)
        department_buttons.addWidget(department_none_btn)
        department_buttons.addStretch(1)
        routing_layout.addLayout(department_buttons)

        routing_note = QLabel(
            "Department IDs are fixed from Current RMS: 1000083 Power, 1000012 Rigging, 1000010 Technology, "
            "1000011 TV Lights. No Prep Department catches changed products where the custom field is blank."
        )
        routing_note.setWordWrap(True)
        routing_note.setObjectName("SectionSubtitle")
        routing_layout.addWidget(routing_note)
        layout.addWidget(routing_panel)

        sounds_panel, sounds_layout = make_panel(
            "Sound Library",
            "Import WAV files to the manager and use the exact filename in alert rules that include sound.",
        )
        sound_buttons = QHBoxLayout()
        import_sound_btn = QPushButton("Import WAV Sound")
        open_sounds_btn = QPushButton("Open Sounds Folder")
        import_sound_btn.clicked.connect(self.import_sound_file)
        open_sounds_btn.clicked.connect(self.open_sounds_folder)
        sound_buttons.addWidget(import_sound_btn)
        sound_buttons.addWidget(open_sounds_btn)
        sound_buttons.addStretch(1)
        sounds_layout.addLayout(sound_buttons)
        layout.addWidget(sounds_panel)

        test_box, test_layout = make_panel(
            "Test Notifications",
            "Send a popup, a silent popup, or a sound test to only the checked Pi screens below.",
        )

        test_form = QFormLayout()
        self.test_title_input = QLineEdit("Test Notification")
        self.test_message_input = QTextEdit()
        self.test_message_input.setPlaceholderText("Type the popup text you want to show on the Pis.")
        self.test_message_input.setMinimumHeight(92)
        self.test_sound_input = QLineEdit("job-today.wav")
        self.test_delivery_input = QComboBox()
        self.populate_delivery_combo(self.test_delivery_input, {"delivery_mode": "popup_sound"})

        test_form.addRow("Title", self.test_title_input)
        test_form.addRow("Message", self.test_message_input)
        test_form.addRow("Delivery", self.test_delivery_input)
        test_form.addRow("Sound file", self.test_sound_input)
        test_layout.addLayout(test_form)

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
            "This uses the same Pi alert route as live notifications, but only sends to the checked screens above."
        )
        test_note.setWordWrap(True)
        test_layout.addWidget(test_note)
        layout.addWidget(test_box)
        layout.addStretch(1)
        self.refresh_test_devices()

    def settings_payload(self):
        event_types = {}
        for event_key, inputs in self.event_inputs.items():
            delivery = self.delivery_flags(inputs["delivery"].currentData())
            event_types[event_key] = {
                "enabled": inputs["enabled"].isChecked(),
                "show_popup": delivery["show_popup"],
                "play_sound": delivery["play_sound"],
                "delivery_mode": delivery["delivery_mode"],
                "send_email": inputs["send_email"].isChecked(),
                "sound": inputs["sound"].text().strip(),
            }
        event_routes = self.route_table_payload(self.event_route_table)
        if event_routes is None:
            event_routes = self.original_event_routes
        department_routes = self.route_table_payload(self.department_route_table)
        if department_routes is None:
            department_routes = self.original_department_routes

        return {
            "poll_seconds": self.poll_seconds_input.value(),
            "startup_sound_suppress_seconds": self.startup_suppress_input.value(),
            "quiet_hours_start": self.quiet_start_input.value(),
            "quiet_hours_end": self.quiet_end_input.value(),
            "history_limit": self.history_limit_input.value(),
            "event_routes": event_routes,
            "email": {
                "enabled": self.email_enabled.isChecked(),
                "smtp_host": self.smtp_host_input.text().strip(),
                "smtp_port": self.smtp_port_input.value(),
                "smtp_security": self.smtp_security_input.currentText(),
                "username": self.smtp_username_input.text().strip(),
                "password": self.smtp_password_input.text(),
                "from_address": self.smtp_from_address_input.text().strip(),
                "from_name": self.smtp_from_name_input.text().strip(),
                "recipients": self.parse_recipients(self.email_recipients_input.toPlainText()),
                "subject_template": self.email_subject_template_input.text().strip(),
                "body_template": self.email_body_template_input.toPlainText(),
            },
            "department_routing": {
                "enabled": self.department_routing_enabled.isChecked(),
                "field_names": self.parse_csv(self.department_field_names_input.text()),
                "send_unknown_to_all": False if self.routing_devices else self.original_unknown_all,
                "routes": department_routes,
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

    def test_email(self):
        payload = self.settings_payload()
        self.state.save_settings({"alerts": payload})
        success, message = self.state.test_email_alerts(payload)
        if success:
            QMessageBox.information(self, "SMTP Test Email", message)
        else:
            QMessageBox.warning(self, "SMTP Test Email Failed", message)

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

        delivery = self.delivery_flags(self.test_delivery_input.currentData())
        if delivery["play_sound"] and not self.test_sound_input.text().strip():
            QMessageBox.warning(self, "Test Notification", "Choose a sound file or use Popup only (silent).")
            return
        if not delivery["show_popup"] and not delivery["play_sound"]:
            QMessageBox.warning(self, "Test Notification", "Choose a delivery mode that shows a popup or plays a sound.")
            return

        success, message = self.state.send_test_notification(
            title=self.test_title_input.text().strip(),
            message=self.test_message_input.toPlainText(),
            sound_name=self.test_sound_input.text().strip(),
            play_sound=delivery["play_sound"],
            show_popup=delivery["show_popup"],
            device_ids=device_ids,
        )
        if success:
            QMessageBox.information(self, "Test Notification", message)
        else:
            QMessageBox.warning(self, "Test Notification", message)

    def send_category_test_notification(self, event_key, label):
        device_ids = self.selected_test_device_ids()
        if not device_ids:
            QMessageBox.warning(self, "Test Alert", "Select at least one Pi screen to send the test to.")
            return

        inputs = self.event_inputs.get(event_key, {})
        delivery = self.delivery_flags(inputs.get("delivery").currentData() if inputs.get("delivery") else "popup_sound")
        sound_name = inputs.get("sound").text().strip() if inputs.get("sound") else ""
        if delivery["play_sound"] and not sound_name:
            QMessageBox.warning(self, "Test Alert", f"{label} is set to play sound but has no sound file configured.")
            return
        if not delivery["show_popup"] and not delivery["play_sound"]:
            QMessageBox.warning(self, "Test Alert", f"{label} is set to log/email only, so there is nothing to send to a Pi.")
            return

        success, message = self.state.send_test_notification(
            title=f"Test: {label}",
            message=f"Testing {label} notification delivery.",
            sound_name=sound_name,
            play_sound=delivery["play_sound"],
            show_popup=delivery["show_popup"],
            device_ids=device_ids,
        )
        if success:
            QMessageBox.information(self, "Test Alert", message)
        else:
            QMessageBox.warning(self, "Test Alert", message)


class ManagerInfoCard(QFrame):
    TONE_COLORS = {
        "good": "#1c6b57",
        "warn": "#d48b12",
        "bad": "#b42318",
        "info": "#244e73",
        "muted": "#7b8b9a",
    }

    def __init__(self, title):
        super().__init__()
        self.setObjectName("ManagerInfoCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(5)

        self.title_label = QLabel(title.upper())
        self.title_label.setStyleSheet("color:#315b7c; font-size:11px; font-weight:900; letter-spacing:1px;")
        self.value_label = QLabel("Loading")
        self.value_label.setStyleSheet("color:#17212b; font-size:19px; font-weight:900;")
        self.value_label.setWordWrap(True)
        self.detail_label = QLabel("")
        self.detail_label.setStyleSheet("color:#516579; font-size:12px; font-weight:650;")
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
            f"QFrame#ManagerInfoCard {{ background:#ffffff; border:1px solid #d1dce6; "
            f"border-left:7px solid {color}; border-radius:12px; }}"
        )
        self.value_label.setText(str(value or "Unknown"))
        self.detail_label.setText(str(detail or ""))


class ManagerPiTab(QWidget):
    command_finished = Signal(str)
    refresh_result_ready = Signal(object)

    def __init__(self, state):
        super().__init__()
        self.state = state
        self.refresh_in_progress = False
        self.active = True
        layout = make_scroll_page(self)
        add_page_heading(
            layout,
            "Manager Pi",
            "Backend health, software updates, service restarts, reboot controls, and remote password changes.",
        )

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
        self.command_status.setObjectName("StatusStrip")
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
        self.refresh_result_ready.connect(self.handle_refresh_result)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(8000)
        self.refresh()

    def make_section(self, title, subtitle=""):
        return make_panel(title, subtitle)

    def set_active(self, active):
        self.active = bool(active)
        if self.active:
            self.timer.start(8000)
            self.refresh()
        else:
            self.timer.stop()

    def refresh(self):
        if self.refresh_in_progress:
            return
        self.refresh_in_progress = True
        Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self):
        try:
            status = self.state.get_manager_status()
        except Exception as error:
            safe_emit(self.refresh_result_ready, {"ok": False, "error": str(error)})
            return
        safe_emit(self.refresh_result_ready, {"ok": True, "status": status})

    def handle_refresh_result(self, result):
        self.refresh_in_progress = False
        if not result.get("ok"):
            error = result.get("error", "Unknown error")
            self.connection_card.set_content("Offline", f"Could not read Manager Pi status: {error}", "bad")
            self.software_card.set_content("Unknown", "No update status available.", "muted")
            self.services_card.set_content("Unknown", "No service status available.", "muted")
            self.security_card.set_content("Unknown", "No security status available.", "muted")
            self.manager_update_card.set_content("Unknown", "No update status available.", "muted")
            self.version_card.set_content("Unknown", "No version status available.", "muted")
            return
        self.apply_manager_status(result.get("status", {}) or {})

    def apply_manager_status(self, status):
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
            safe_emit(self.command_finished, message)

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
    refresh_result_ready = Signal(object)

    COLUMNS = [
        "ID",
        "Name",
        "IP",
        "Screen",
        "Scale",
        "Layout",
        "Version",
        "Update",
        "State",
        "Audio",
        "Activity",
        "Last Seen",
    ]
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
    AUDIO_COLORS = {
        "Audio OK": "#2e7d32",
        "Audio Issue": "#b71c1c",
        "Check stale": "#f9a825",
        "Not checked": "#455a64",
    }

    def __init__(self, state):
        super().__init__()
        self.setObjectName("WarehousePage")
        self.state = state
        self.refresh_in_progress = False
        self.active = True
        self.last_refresh_signature = ""
        layout = make_scroll_page(self, margins=(12, 12, 12, 18), spacing=10)
        add_page_heading(
            layout,
            "Dashboards",
            "Monitor registered dashboard screens and send targeted display, audio, update, restart, and recovery commands.",
        )

        self.update_status = make_status_label("Checking GitHub update status...")
        layout.addWidget(self.update_status)

        fleet_panel, fleet_layout = make_panel(
            "Registered Dashboards",
            "Select one or more dashboard screens before sending targeted commands.",
        )
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.MultiSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setMinimumHeight(260)
        tune_table(self.table)
        fleet_layout.addWidget(self.table)
        layout.addWidget(fleet_panel)

        controls_panel, controls_layout = make_panel(
            "Selected Dashboard Actions",
            "Use these commands for the highlighted dashboard rows only.",
        )
        nav_label = QLabel("Screen navigation")
        nav_label.setObjectName("SectionSubtitle")
        controls_layout.addWidget(nav_label)
        screen_actions = (
            ("Show Home", "overview"),
            ("Show Today", "today"),
            ("Show Tomorrow", "tomorrow"),
            ("Show Prep", "prep"),
            ("Show Outstanding", "outstanding"),
            ("Show Unreturned", "unreturned"),
            ("Show Quarantines", "quarantines"),
            ("Show Notification History", "notifications"),
        )
        for screen_action_group in (screen_actions[:4], screen_actions[4:]):
            screen_buttons = QHBoxLayout()
            for label, screen in screen_action_group:
                btn = QPushButton(label)
                btn.clicked.connect(lambda _checked=False, target=screen: self.send_screen(target))
                screen_buttons.addWidget(btn)
            screen_buttons.addStretch(1)
            controls_layout.addLayout(screen_buttons)

        command_label = QLabel("Device setup and software")
        command_label.setObjectName("SectionSubtitle")
        controls_layout.addWidget(command_label)
        primary_command_buttons = QHBoxLayout()
        rename_btn = QPushButton("Rename Pi")
        display_size_btn = QPushButton("Set Display Size")
        layout_mode_btn = QPushButton("Set Layout Mode")
        restart_btn = QPushButton("Restart Display App")
        update_btn = QPushButton("Update Pi From GitHub")
        sound_check_btn = QPushButton("Run Sound Check")
        set_audio_btn = QPushButton("Set Audio Output")
        sound_loop_start_btn = QPushButton("Start Repeating Sound")
        sound_loop_stop_btn = QPushButton("Stop Repeating Sound")
        update_all_btn = mark_primary(QPushButton("Update All Pis + Manager"))
        check_updates_btn = QPushButton("Check GitHub Updates")
        reboot_btn = mark_danger(QPushButton("Reboot Pi"))
        remove_btn = mark_danger(QPushButton("Remove Selected"))
        refresh_btn = QPushButton("Refresh List")
        rename_btn.clicked.connect(self.rename_selected_pi)
        display_size_btn.clicked.connect(self.set_display_size_selected)
        layout_mode_btn.clicked.connect(self.set_layout_mode_selected)
        restart_btn.clicked.connect(lambda: self.send_action("restart"))
        update_btn.clicked.connect(lambda: self.send_action("update"))
        sound_check_btn.clicked.connect(lambda: self.send_action("sound_check"))
        set_audio_btn.clicked.connect(self.set_audio_selected)
        sound_loop_start_btn.clicked.connect(self.start_repeating_sound)
        sound_loop_stop_btn.clicked.connect(lambda: self.send_action("sound_loop_stop"))
        update_all_btn.clicked.connect(self.update_all)
        check_updates_btn.clicked.connect(self.check_updates_now)
        reboot_btn.clicked.connect(lambda: self.send_action("reboot"))
        remove_btn.clicked.connect(self.remove_selected_pis)
        refresh_btn.clicked.connect(self.refresh)
        primary_command_buttons.addWidget(rename_btn)
        primary_command_buttons.addWidget(display_size_btn)
        primary_command_buttons.addWidget(layout_mode_btn)
        primary_command_buttons.addWidget(restart_btn)
        primary_command_buttons.addWidget(update_btn)
        primary_command_buttons.addStretch(1)
        controls_layout.addLayout(primary_command_buttons)

        utility_command_buttons = QHBoxLayout()
        utility_command_buttons.addWidget(sound_check_btn)
        utility_command_buttons.addWidget(set_audio_btn)
        utility_command_buttons.addStretch(1)
        controls_layout.addLayout(utility_command_buttons)

        sound_label = QLabel("Audio walk-test")
        sound_label.setObjectName("SectionSubtitle")
        controls_layout.addWidget(sound_label)
        sound_test_layout = QHBoxLayout()
        self.sound_loop_input = QLineEdit("job-changes.wav")
        self.sound_loop_input.setPlaceholderText("Sound file, e.g. job-changes.wav")
        sound_test_layout.addWidget(QLabel("Repeating sound"))
        sound_test_layout.addWidget(self.sound_loop_input, 1)
        sound_test_layout.addWidget(sound_loop_start_btn)
        sound_test_layout.addWidget(sound_loop_stop_btn)
        controls_layout.addLayout(sound_test_layout)

        service_buttons = QHBoxLayout()
        service_buttons.addWidget(check_updates_btn)
        service_buttons.addWidget(refresh_btn)
        service_buttons.addWidget(update_all_btn)
        service_buttons.addStretch(1)
        service_buttons.addWidget(reboot_btn)
        service_buttons.addWidget(remove_btn)
        controls_layout.addLayout(service_buttons)
        layout.addWidget(controls_panel)

        maintenance_settings = self.state.get_settings(include_secret=True).get("maintenance", {}) or {}
        maintenance_panel, maintenance_panel_layout = make_panel(
            "Maintenance Screen",
            "Blank selected dashboard screens while you work behind the scenes.",
        )
        maintenance_layout = QGridLayout()
        self.maintenance_text_input = QTextEdit()
        self.maintenance_text_input.setPlainText(
            str(maintenance_settings.get("text") or "Maintenance in progress\nPlease wait")
        )
        self.maintenance_text_input.setMinimumHeight(58)
        self.maintenance_text_input.setPlaceholderText("Text to show while the screen is blanked.")
        self.maintenance_background_input = QLineEdit(str(maintenance_settings.get("background") or "#050505"))
        self.maintenance_foreground_input = QLineEdit(str(maintenance_settings.get("foreground") or "#ffffff"))
        pick_background_btn = QPushButton("Pick Background")
        pick_text_btn = QPushButton("Pick Text Colour")
        show_maintenance_btn = mark_primary(QPushButton("Show Maintenance Screen"))
        hide_maintenance_btn = QPushButton("Hide Maintenance Screen")
        pick_background_btn.clicked.connect(
            lambda: self.pick_colour(self.maintenance_background_input, "Pick Maintenance Background")
        )
        pick_text_btn.clicked.connect(
            lambda: self.pick_colour(self.maintenance_foreground_input, "Pick Maintenance Text Colour")
        )
        show_maintenance_btn.clicked.connect(self.show_maintenance_screen)
        hide_maintenance_btn.clicked.connect(lambda: self.send_action("maintenance_hide"))

        maintenance_layout.addWidget(QLabel("Maintenance text"), 0, 0)
        maintenance_layout.addWidget(self.maintenance_text_input, 0, 1, 2, 3)
        maintenance_layout.addWidget(QLabel("Background"), 2, 0)
        maintenance_layout.addWidget(self.maintenance_background_input, 2, 1)
        maintenance_layout.addWidget(pick_background_btn, 2, 2)
        maintenance_layout.addWidget(QLabel("Text colour"), 3, 0)
        maintenance_layout.addWidget(self.maintenance_foreground_input, 3, 1)
        maintenance_layout.addWidget(pick_text_btn, 3, 2)
        maintenance_layout.addWidget(show_maintenance_btn, 4, 1)
        maintenance_layout.addWidget(hide_maintenance_btn, 4, 2)
        maintenance_layout.setColumnStretch(3, 1)
        maintenance_panel_layout.addLayout(maintenance_layout)
        layout.addWidget(maintenance_panel)

        night_sleep_settings = self.state.get_settings(include_secret=True).get("night_sleep", {}) or {}
        sleep_panel, sleep_panel_layout = make_panel(
            "Overnight Sleep",
            "Schedule all dashboard screens to show a sleeping message while the manager pauses overnight work.",
        )
        sleep_layout = QGridLayout()
        self.sleep_enabled_input = QCheckBox("Enable scheduled overnight sleep for all dashboard Pis")
        self.sleep_enabled_input.setChecked(bool(night_sleep_settings.get("enabled", False)))
        self.sleep_start_input = QLineEdit(str(night_sleep_settings.get("start") or "19:00"))
        self.sleep_end_input = QLineEdit(str(night_sleep_settings.get("end") or "06:00"))
        self.sleep_text_input = QTextEdit()
        self.sleep_text_input.setPlainText(
            str(night_sleep_settings.get("text") or "Manager is sleeping\nBoards will wake in the morning")
        )
        self.sleep_text_input.setMinimumHeight(58)
        self.sleep_text_input.setPlaceholderText("Text to show overnight while the manager is sleeping.")
        self.sleep_background_input = QLineEdit(str(night_sleep_settings.get("background") or "#02060a"))
        self.sleep_foreground_input = QLineEdit(str(night_sleep_settings.get("foreground") or "#b7f7d4"))
        pick_sleep_background_btn = QPushButton("Pick Background")
        pick_sleep_text_btn = QPushButton("Pick Text Colour")
        apply_sleep_btn = mark_primary(QPushButton("Apply Sleep Schedule"))
        pick_sleep_background_btn.clicked.connect(
            lambda: self.pick_colour(self.sleep_background_input, "Pick Sleep Background")
        )
        pick_sleep_text_btn.clicked.connect(
            lambda: self.pick_colour(self.sleep_foreground_input, "Pick Sleep Text Colour")
        )
        apply_sleep_btn.clicked.connect(self.apply_night_sleep_schedule)

        sleep_layout.addWidget(self.sleep_enabled_input, 0, 0, 1, 4)
        sleep_layout.addWidget(QLabel("Sleep from"), 1, 0)
        sleep_layout.addWidget(self.sleep_start_input, 1, 1)
        sleep_layout.addWidget(QLabel("until"), 1, 2)
        sleep_layout.addWidget(self.sleep_end_input, 1, 3)
        sleep_layout.addWidget(QLabel("Sleeping text"), 2, 0)
        sleep_layout.addWidget(self.sleep_text_input, 2, 1, 2, 3)
        sleep_layout.addWidget(QLabel("Background"), 4, 0)
        sleep_layout.addWidget(self.sleep_background_input, 4, 1)
        sleep_layout.addWidget(pick_sleep_background_btn, 4, 2)
        sleep_layout.addWidget(QLabel("Text colour"), 5, 0)
        sleep_layout.addWidget(self.sleep_foreground_input, 5, 1)
        sleep_layout.addWidget(pick_sleep_text_btn, 5, 2)
        sleep_layout.addWidget(apply_sleep_btn, 6, 1)
        sleep_layout.setColumnStretch(3, 1)
        sleep_panel_layout.addLayout(sleep_layout)
        layout.addWidget(sleep_panel)

        watchdog_settings = self.state.get_settings(include_secret=True).get("connection_watchdog", {}) or {}
        watchdog_panel, watchdog_panel_layout = make_panel(
            "Auto-Recovery",
            "Optional reboot guard for selected dashboards that repeatedly lose contact with the Manager Pi.",
        )
        watchdog_layout = QGridLayout()
        self.watchdog_enabled_input = QCheckBox("Reboot selected Pis after sustained Manager Pi connection loss")
        self.watchdog_enabled_input.setChecked(bool(watchdog_settings.get("enabled", False)))
        self.watchdog_failure_minutes_input = QSpinBox()
        self.watchdog_failure_minutes_input.setRange(2, 120)
        self.watchdog_failure_minutes_input.setValue(int(watchdog_settings.get("failure_minutes", 10) or 10))
        self.watchdog_cooldown_minutes_input = QSpinBox()
        self.watchdog_cooldown_minutes_input.setRange(15, 720)
        self.watchdog_cooldown_minutes_input.setValue(int(watchdog_settings.get("cooldown_minutes", 60) or 60))
        apply_watchdog_btn = QPushButton("Apply Connection Watchdog")
        apply_watchdog_btn.clicked.connect(self.apply_connection_watchdog)
        watchdog_layout.addWidget(self.watchdog_enabled_input, 0, 0, 1, 3)
        watchdog_layout.addWidget(QLabel("Reboot after lost connection for"), 1, 0)
        watchdog_layout.addWidget(self.watchdog_failure_minutes_input, 1, 1)
        watchdog_layout.addWidget(QLabel("minutes"), 1, 2)
        watchdog_layout.addWidget(QLabel("Minimum time between watchdog reboots"), 2, 0)
        watchdog_layout.addWidget(self.watchdog_cooldown_minutes_input, 2, 1)
        watchdog_layout.addWidget(QLabel("minutes"), 2, 2)
        watchdog_layout.addWidget(apply_watchdog_btn, 3, 1)
        watchdog_layout.setColumnStretch(3, 1)
        watchdog_panel_layout.addLayout(watchdog_layout)
        layout.addWidget(watchdog_panel)

        self.status = make_status_label("Waiting for Pi screens to register...")
        layout.addWidget(self.status)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(6000)
        self.command_finished.connect(self.on_command_finished)
        self.refresh_result_ready.connect(self.handle_refresh_result)
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

    def set_active(self, active):
        self.active = bool(active)
        if self.active:
            self.timer.start(6000)
            self.refresh()
        else:
            self.timer.stop()

    def refresh(self):
        if self.refresh_in_progress:
            return
        self.refresh_in_progress = True
        Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self):
        try:
            devices = self.state.list_devices()
            update_status = self.state.get_update_status()
        except Exception as error:
            safe_emit(self.refresh_result_ready, {"ok": False, "error": str(error)})
            return
        safe_emit(self.refresh_result_ready, {"ok": True, "devices": devices, "update_status": update_status})

    def handle_refresh_result(self, result):
        self.refresh_in_progress = False
        if not result.get("ok"):
            self.status.setText(f"Could not refresh Pi list: {result.get('error', 'unknown error')}")
            return
        self.apply_devices(result.get("devices", []) or [], result.get("update_status", {}) or {})

    def apply_devices(self, devices, update_status):
        stable_devices = []
        for device in devices:
            stable_devices.append(
                {
                    key: value
                    for key, value in device.items()
                    if key not in {"last_seen", "status_updated_at", "audio_checked_at"}
                }
            )
        signature = repr(stable_devices) + repr(update_status)
        if signature == self.last_refresh_signature:
            self.update_status.setText(self.format_update_status(update_status))
            return
        self.last_refresh_signature = signature
        online_count = 0
        offline_count = 0
        update_count = 0
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(devices))
            for row, device in enumerate(devices):
                values = [
                    device.get("id", ""),
                    device.get("name", ""),
                    device.get("ip", ""),
                    device.get("screen", ""),
                    f"{device.get('display_scale', 100)}%",
                    str(device.get("compact_layout") or "auto").title(),
                    device.get("version", ""),
                    device.get("update", ""),
                    device.get("state", ""),
                    device.get("audio", ""),
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
                    elif self.COLUMNS[column] == "Audio":
                        color = self.AUDIO_COLORS.get(str(value), "")
                        if color:
                            item.setBackground(QColor(color))
                            item.setForeground(QColor("#111111" if str(value) == "Check stale" else "#ffffff"))
                        item.setToolTip(str(device.get("audio_detail", "")))
                    elif self.COLUMNS[column] == "Update" and str(value).startswith("Available"):
                        item.setBackground(QColor("#d48b12"))
                        item.setForeground(QColor("#111111"))
                    self.table.setItem(row, column, item)
            self.table.resizeColumnsToContents()
        finally:
            self.table.setUpdatesEnabled(True)
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
            safe_emit(self.command_finished, message)

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

    def set_layout_mode_selected(self):
        if not self.selected_device_ids():
            QMessageBox.warning(self, "No Pi Selected", "Select one or more Pi screens first.")
            return

        mode, accepted = QInputDialog.getItem(
            self,
            "Set Layout Mode",
            "Choose the display layout mode:\nAuto uses compact layout on small pixel screens.",
            ["auto", "compact", "standard"],
            0,
            False,
        )
        if not accepted:
            return

        device_ids = self.selected_device_ids()
        self.state.queue_command(device_ids, "set_compact_layout", compact_layout=mode)
        self.status.setText(f"Queued {mode} layout mode for {len(device_ids)} Pi screen(s).")

    def start_repeating_sound(self):
        sound_name = self.sound_loop_input.text().strip() or "job-changes.wav"
        self.send_action("sound_loop_start", sound_name=sound_name)

    def set_audio_selected(self):
        if not self.selected_device_ids():
            QMessageBox.warning(self, "No Pi Selected", "Select one or more Pi screens first.")
            return

        output, ok = QInputDialog.getItem(
            self,
            "Set Audio Output",
            "Choose audio output mode:",
            ["auto", "hdmi", "analog"],
            0,
            False,
        )
        if not ok:
            return
        volume, ok = QInputDialog.getInt(
            self,
            "Set Audio Volume",
            "Volume percent:",
            100,
            0,
            100,
            5,
        )
        if not ok:
            return
        self.send_action("set_audio", audio_output=output, audio_volume=volume)

    def pick_colour(self, target_input, title):
        current = QColor(target_input.text().strip())
        if not current.isValid():
            current = QColor("#050505")
        color = QColorDialog.getColor(current, self, title)
        if color.isValid():
            target_input.setText(color.name())

    def maintenance_payload(self):
        text = self.maintenance_text_input.toPlainText().strip() or "Maintenance in progress\nPlease wait"
        background = self.maintenance_background_input.text().strip() or "#050505"
        foreground = self.maintenance_foreground_input.text().strip() or "#ffffff"
        if not QColor(background).isValid():
            raise ValueError("Maintenance background colour is not valid. Use a colour like #050505.")
        if not QColor(foreground).isValid():
            raise ValueError("Maintenance text colour is not valid. Use a colour like #ffffff.")
        return {
            "text": text,
            "background": QColor(background).name(),
            "foreground": QColor(foreground).name(),
        }

    def normalise_sleep_time(self, text, fallback, label):
        raw = str(text or fallback).strip().replace(".", ":")
        parts = raw.split(":")
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            raise ValueError(f"{label} must be in 24-hour HH:MM format, for example 19:00.")
        hours = int(parts[0])
        minutes = int(parts[1])
        if hours < 0 or hours > 23 or minutes < 0 or minutes > 59:
            raise ValueError(f"{label} must be a valid 24-hour time.")
        return f"{hours:02d}:{minutes:02d}"

    def night_sleep_payload(self):
        start = self.normalise_sleep_time(self.sleep_start_input.text(), "19:00", "Sleep start")
        end = self.normalise_sleep_time(self.sleep_end_input.text(), "06:00", "Sleep end")
        text = self.sleep_text_input.toPlainText().strip() or "Manager is sleeping\nBoards will wake in the morning"
        background = self.sleep_background_input.text().strip() or "#02060a"
        foreground = self.sleep_foreground_input.text().strip() or "#b7f7d4"
        if not QColor(background).isValid():
            raise ValueError("Sleep background colour is not valid. Use a colour like #02060a.")
        if not QColor(foreground).isValid():
            raise ValueError("Sleep text colour is not valid. Use a colour like #b7f7d4.")
        return {
            "enabled": self.sleep_enabled_input.isChecked(),
            "start": start,
            "end": end,
            "text": text,
            "background": QColor(background).name(),
            "foreground": QColor(foreground).name(),
        }

    def apply_night_sleep_schedule(self):
        try:
            payload = self.night_sleep_payload()
        except ValueError as error:
            QMessageBox.warning(self, "Night Sleep", str(error))
            return

        self.state.save_settings({"night_sleep": payload})
        self.state.refresh_dashboard()
        state_text = "enabled" if payload["enabled"] else "disabled"
        self.status.setText(
            f"Night sleep {state_text}: {payload['start']} to {payload['end']}. Manager sleep state synced."
        )

    def show_maintenance_screen(self):
        device_ids = self.selected_device_ids()
        if not device_ids:
            QMessageBox.warning(self, "No Pi Selected", "Select one or more Pi screens first.")
            return

        try:
            payload = self.maintenance_payload()
        except ValueError as error:
            QMessageBox.warning(self, "Maintenance Screen", str(error))
            return

        self.state.save_settings({"maintenance": payload})
        self.state.queue_command(device_ids, "maintenance_show", **payload)
        self.status.setText(f"Queued maintenance screen for {len(device_ids)} Pi screen(s).")

    def connection_watchdog_payload(self):
        failure_minutes = self.watchdog_failure_minutes_input.value()
        cooldown_minutes = self.watchdog_cooldown_minutes_input.value()
        return {
            "enabled": self.watchdog_enabled_input.isChecked(),
            "failure_minutes": failure_minutes,
            "cooldown_minutes": cooldown_minutes,
            "failure_reboot_seconds": failure_minutes * 60,
            "reboot_cooldown_seconds": cooldown_minutes * 60,
        }

    def apply_connection_watchdog(self):
        device_ids = self.selected_device_ids()
        if not device_ids:
            QMessageBox.warning(self, "No Pi Selected", "Select one or more Pi screens first.")
            return

        payload = self.connection_watchdog_payload()
        self.state.save_settings(
            {
                "connection_watchdog": {
                    "enabled": payload["enabled"],
                    "failure_minutes": payload["failure_minutes"],
                    "cooldown_minutes": payload["cooldown_minutes"],
                }
            }
        )
        self.state.queue_command(device_ids, "set_connection_watchdog", **payload)
        state_text = "enabled" if payload["enabled"] else "disabled"
        self.status.setText(f"Queued connection watchdog {state_text} for {len(device_ids)} Pi screen(s).")

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

    def send_action(self, action, screen=None, **extra):
        device_ids = self.selected_device_ids()
        if not device_ids:
            QMessageBox.warning(self, "No Pi Selected", "Select one or more Pi screens first.")
            return

        self.state.queue_command(device_ids, action, screen=screen, **extra)
        self.status.setText(f"Queued {action} for {len(device_ids)} Pi screen(s).")


class ActivityConsoleTab(QWidget):
    refresh_result_ready = Signal(object)

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
        self.refresh_in_progress = False
        self.active = True
        self.last_refresh_signature = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 14)
        layout.setSpacing(10)
        add_page_heading(
            layout,
            "Activity Log",
            "Manager activity, diagnostics, update events, and behind-the-scenes notification history.",
        )

        controls_panel, controls_layout = make_toolbar_panel()
        controls = QHBoxLayout()
        self.category_filter = QComboBox()
        self.category_filter.addItems(
            ["All", "Current RMS", "Pis", "Audio", "Notifications", "Updates", "Commands", "Settings", "Sleep", "Manager"]
        )
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
        self.timer.start(5000)
        self.refresh_result_ready.connect(self.handle_refresh_result)
        self.refresh()

    def set_active(self, active):
        self.active = bool(active)
        if self.active:
            self.timer.start(5000)
            self.refresh()
        else:
            self.timer.stop()

    def refresh(self):
        if self.refresh_in_progress:
            return
        self.refresh_in_progress = True
        category = self.category_filter.currentText()
        level = self.level_filter.currentText()
        Thread(target=self._refresh_worker, args=(category, level), daemon=True).start()

    def _refresh_worker(self, category, level):
        try:
            entries = self.state.list_activity(
                category=category,
                level=level,
                limit=500,
            )
        except Exception as error:
            safe_emit(self.refresh_result_ready, {"ok": False, "error": str(error)})
            return
        safe_emit(self.refresh_result_ready, {"ok": True, "entries": entries})

    def handle_refresh_result(self, result):
        self.refresh_in_progress = False
        if not result.get("ok"):
            self.status.setText(f"Could not refresh console: {result.get('error', 'unknown error')}")
            return
        self.apply_entries(result.get("entries", []) or [])

    def apply_entries(self, entries):
        signature = repr(entries)
        if signature == self.last_refresh_signature:
            return
        self.last_refresh_signature = signature
        self.table.setUpdatesEnabled(False)
        try:
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
        finally:
            self.table.setUpdatesEnabled(True)
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
        tabs.addTab(ConnectionTab(state), "Setup")
        tabs.addTab(CurrentRMSTab(state), "Data Source")
        tabs.addTab(AlertsTab(state), "Notifications")
        tabs.addTab(ManagerPiTab(state), "Manager Pi")
        tabs.addTab(PiScreensTab(state), "Dashboards")
        tabs.addTab(ActivityConsoleTab(state), "Activity Log")
        self.setCentralWidget(tabs)
        self.tabs = tabs
        tabs.currentChanged.connect(self.on_tab_changed)
        QTimer.singleShot(0, lambda: self.on_tab_changed(tabs.currentIndex()))

    def on_tab_changed(self, index):
        for tab_index in range(self.tabs.count()):
            widget = self.tabs.widget(tab_index)
            if hasattr(widget, "set_active"):
                widget.set_active(tab_index == index)

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

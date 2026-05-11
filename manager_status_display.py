from datetime import datetime
import re
import socket
import sys

import requests
from PySide6.QtCore import QEvent, QObject, QPoint, QSize, QTimer, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QScrollArea,
    QScroller,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app_version import CURRENT_VERSION


BACKEND_URL = "http://127.0.0.1:8765"

TONE_COLORS = {
    "good": "#5fe29a",
    "warn": "#ffd166",
    "bad": "#ff6b6b",
    "info": "#5cc8ff",
    "muted": "#7f93a0",
}

STATE_TONES = {
    "online": "good",
    "active": "good",
    "display starting": "info",
    "display restarting": "info",
    "rebooting": "warn",
    "renaming": "warn",
    "switching screen": "info",
    "updating": "warn",
    "update failed": "bad",
    "offline": "bad",
    "unknown": "muted",
}


def local_addresses():
    addresses = set()
    hostname = socket.gethostname()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route_socket:
            route_socket.connect(("8.8.8.8", 80))
            address = route_socket.getsockname()[0]
            if address and not address.startswith("127.") and not address.startswith("169.254."):
                addresses.add(address)
    except Exception:
        pass
    try:
        address = socket.gethostbyname(hostname)
        if address and not address.startswith("127.") and not address.startswith("169.254."):
            addresses.add(address)
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            address = info[4][0]
            if address and not address.startswith("127.") and not address.startswith("169.254."):
                addresses.add(address)
    except Exception:
        pass
    return sorted(addresses)


def clean_text(value, fallback=""):
    text = str(value or "").strip()
    return text or fallback


def tone_color(tone):
    return TONE_COLORS.get(tone, TONE_COLORS["muted"])


def service_tone(value):
    text = clean_text(value, "unknown").lower()
    if text == "active":
        return "good"
    if text in {"activating", "reloading"}:
        return "warn"
    if text in {"inactive", "failed"}:
        return "bad"
    return "muted"


def state_tone(value):
    text = clean_text(value, "unknown").lower()
    return STATE_TONES.get(text, "muted")


def format_time(value):
    try:
        return datetime.fromisoformat(str(value)).strftime("%H:%M:%S")
    except Exception:
        return clean_text(value)


def refresh_duration(message):
    match = re.search(r"finished in\s+(\d+)ms", clean_text(message), re.I)
    if not match:
        return ""
    milliseconds = int(match.group(1))
    return f"{milliseconds / 1000:.1f}s"


def available_font(preferred):
    families = set(QFontDatabase.families())
    for family in preferred:
        if family in families:
            return family
    return QApplication.font().family()


def event_position(event):
    if hasattr(event, "position"):
        return event.position().toPoint()
    if hasattr(event, "pos"):
        return event.pos()
    return QPoint()


class DragScrollFilter(QObject):
    def __init__(self, scroll_widget):
        super().__init__(scroll_widget)
        self.scroll_widget = scroll_widget
        self.pressed = False
        self.dragging = False
        self.start_pos = QPoint()
        self.last_pos = QPoint()

    def eventFilter(self, obj, event):
        event_type = event.type()
        if event_type == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self.pressed = True
            self.dragging = False
            self.start_pos = event_position(event)
            self.last_pos = self.start_pos
            return False

        if event_type == QEvent.MouseMove and self.pressed and event.buttons() & Qt.LeftButton:
            pos = event_position(event)
            if not self.dragging:
                distance = (pos - self.start_pos).manhattanLength()
                if distance < QApplication.startDragDistance():
                    return False
                self.dragging = True

            delta = pos - self.last_pos
            self.last_pos = pos
            self.scroll_widget.verticalScrollBar().setValue(
                self.scroll_widget.verticalScrollBar().value() - delta.y()
            )
            event.accept()
            return True

        if event_type == QEvent.MouseButtonRelease and self.pressed:
            was_dragging = self.dragging
            self.pressed = False
            self.dragging = False
            if was_dragging:
                event.accept()
                return True

        return False


def enable_touch_scroll(widget):
    viewport = widget.viewport() if hasattr(widget, "viewport") else widget
    viewport.setAttribute(Qt.WA_AcceptTouchEvents, True)
    QScroller.grabGesture(viewport, QScroller.TouchGesture)
    QScroller.grabGesture(viewport, QScroller.LeftMouseButtonGesture)
    drag_filter = DragScrollFilter(widget)
    viewport.installEventFilter(drag_filter)
    widget._warehouse_manager_drag_scroll_filter = drag_filter


class Card(QFrame):
    def __init__(self, object_name="Card"):
        super().__init__()
        self.setObjectName(object_name)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)


class Pill(QLabel):
    def __init__(self, text="", tone="muted"):
        super().__init__(text.upper())
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(28)
        self.set_tone(tone)

    def set_tone(self, tone):
        color = tone_color(tone)
        self.setStyleSheet(
            f"background:{color}; color:#061014; border-radius:14px; "
            "padding:4px 10px; font-size:13px; font-weight:900;"
        )

    def set_text(self, text, tone="muted"):
        self.setText(clean_text(text, "unknown").upper())
        self.set_tone(tone)


class MetricCard(Card):
    def __init__(self, title):
        super().__init__("MetricCard")
        self.tone = "muted"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        self.title_label = QLabel(title.upper())
        self.title_label.setObjectName("MetricTitle")
        self.value_label = QLabel("Waiting")
        self.value_label.setObjectName("MetricValue")
        self.value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.value_label.setWordWrap(True)
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("MetricDetail")
        self.detail_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.detail_label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label, 1)
        layout.addWidget(self.detail_label)
        self.setMinimumHeight(132)
        self.set_content("Waiting", "", "muted")

    def set_content(self, value, detail="", tone="muted"):
        self.tone = tone
        color = tone_color(tone)
        self.setStyleSheet(
            f"QFrame#MetricCard {{ background:#101a20; border:1px solid #263943; "
            f"border-left:8px solid {color}; border-radius:18px; }}"
        )
        self.value_label.setText(clean_text(value, "Waiting"))
        self.detail_label.setText(clean_text(detail))


class InfoPanel(Card):
    def __init__(self, title):
        super().__init__("InfoPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        self.title_label = QLabel(title.upper())
        self.title_label.setObjectName("PanelTitle")
        self.body_label = QLabel("")
        self.body_label.setObjectName("PanelBody")
        self.body_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.body_label, 1)
        self.setMinimumHeight(132)

    def set_body(self, body):
        self.body_label.setText(clean_text(body, "Waiting for data."))


class DeviceRow(Card):
    def __init__(self, device):
        super().__init__("DeviceRow")
        state = clean_text(device.get("state"), "Unknown")
        tone = state_tone(state)
        color = tone_color(tone)
        self.setStyleSheet(
            f"QFrame#DeviceRow {{ background:#101a20; border:1px solid #263943; "
            f"border-left:8px solid {color}; border-radius:18px; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)
        name = QLabel(clean_text(device.get("name") or device.get("id"), "Unnamed screen"))
        name.setObjectName("RowTitle")
        details = QLabel(
            f"{clean_text(device.get('ip'), 'no IP')}  |  "
            f"{clean_text(device.get('screen'), 'unknown screen')}  |  "
            f"v{clean_text(device.get('version'), 'unknown')}"
        )
        details.setObjectName("RowDetail")
        activity = QLabel(clean_text(device.get("activity"), "No activity yet."))
        activity.setObjectName("RowSmall")
        activity.setWordWrap(True)
        text_layout.addWidget(name)
        text_layout.addWidget(details)
        text_layout.addWidget(activity)

        right_layout = QVBoxLayout()
        right_layout.setAlignment(Qt.AlignRight | Qt.AlignTop)
        status_pill = Pill(state, tone)
        update = clean_text(device.get("update"), "Unknown")
        update_tone = "warn" if update.lower().startswith("available") else "good" if update == "Current" else "muted"
        update_pill = Pill(update, update_tone)
        right_layout.addWidget(status_pill)
        right_layout.addWidget(update_pill)
        right_layout.addStretch(1)

        layout.addLayout(text_layout, 1)
        layout.addLayout(right_layout)


class ActivityRow(Card):
    def __init__(self, entry):
        super().__init__("ActivityRow")
        level = clean_text(entry.get("level"), "info").lower()
        tone = "bad" if level == "error" else "warn" if level == "warning" else "info"
        color = tone_color(tone)
        self.setStyleSheet(
            f"QFrame#ActivityRow {{ background:#101a20; border:1px solid #263943; "
            f"border-left:8px solid {color}; border-radius:16px; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(3)
        title = QLabel(f"{clean_text(entry.get('category'), 'Log')}  |  {format_time(entry.get('ts'))}")
        title.setObjectName("RowTitle")
        message = QLabel(clean_text(entry.get("message"), "No message."))
        message.setObjectName("RowDetail")
        message.setWordWrap(True)
        left.addWidget(title)
        left.addWidget(message)

        pill = Pill(level, tone)
        layout.addLayout(left, 1)
        layout.addWidget(pill, 0, Qt.AlignTop)


class LogLine(Card):
    def __init__(self, text):
        super().__init__("LogLine")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        line = QLabel(clean_text(text))
        line.setObjectName("LogText")
        line.setWordWrap(True)
        layout.addWidget(line)


class ManagerStatusWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Warehouse Manager Pi Status")
        self.resize(800, 480)
        self.setAttribute(Qt.WA_AcceptTouchEvents, True)
        self.fetch_errors = {}
        self.ui_font = available_font(("Bahnschrift", "Segoe UI", "Arial", "Noto Sans", "DejaVu Sans"))
        self.mono_font = available_font(("Cascadia Mono", "Consolas", "Courier New", "DejaVu Sans Mono"))
        QApplication.instance().setFont(QFont(self.ui_font))

        root_widget = QWidget()
        root = QVBoxLayout(root_widget)
        root.setContentsMargins(14, 18, 14, 10)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(12)
        title_block = QVBoxLayout()
        title_block.setSpacing(3)
        heading = QLabel("Warehouse Manager")
        heading.setObjectName("Heading")
        heading.setMinimumHeight(36)
        self.subheading = QLabel("Starting manager display...")
        self.subheading.setObjectName("Subheading")
        self.subheading.setMinimumHeight(20)
        self.subheading.setWordWrap(True)
        title_block.addWidget(heading)
        title_block.addWidget(self.subheading)

        self.clock_label = QLabel("")
        self.clock_label.setObjectName("Clock")
        self.clock_label.setMinimumHeight(44)
        self.clock_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        header.addLayout(title_block, 1)
        header.addWidget(self.clock_label)
        root.addLayout(header)
        self.header_divider = QFrame()
        self.header_divider.setObjectName("HeaderDivider")
        self.header_divider.setFrameShape(QFrame.HLine)
        root.addWidget(self.header_divider)
        root.addSpacing(8)

        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.North)
        self.tabs.setDocumentMode(True)
        self.tabs.setAttribute(Qt.WA_AcceptTouchEvents, True)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.tabBar().setAttribute(Qt.WA_AcceptTouchEvents, True)
        root.addWidget(self.tabs, 1)

        self.build_overview_tab()
        self.build_screens_tab()
        self.build_activity_tab()
        self.build_updates_tab()

        self.setCentralWidget(root_widget)
        self.apply_theme()
        self.showFullScreen()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(3000)
        self.refresh()

    def build_overview_tab(self):
        content, layout = self.scrollable_tab()
        layout.setSpacing(10)

        self.system_panel = Card("HeroPanel")
        self.system_panel.setMinimumHeight(112)
        hero = QHBoxLayout(self.system_panel)
        hero.setContentsMargins(18, 16, 18, 16)
        hero.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(4)
        self.system_title = QLabel("Checking system...")
        self.system_title.setObjectName("HeroTitle")
        self.system_detail = QLabel("Waiting for manager backend data.")
        self.system_detail.setObjectName("HeroDetail")
        self.system_detail.setWordWrap(True)
        left.addWidget(self.system_title)
        left.addWidget(self.system_detail)
        self.system_pill = Pill("Starting", "muted")
        hero.addLayout(left, 1)
        hero.addWidget(self.system_pill, 0, Qt.AlignTop)
        layout.addWidget(self.system_panel, 2)

        grid = QGridLayout()
        grid.setSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        grid.setRowStretch(2, 1)
        self.backend_metric = MetricCard("Backend")
        self.screens_metric = MetricCard("Screens")
        self.rms_metric = MetricCard("Current RMS")
        self.update_metric = MetricCard("Updates")
        self.display_metric = MetricCard("Display")
        self.version_metric = MetricCard("Version")
        grid.addWidget(self.backend_metric, 0, 0)
        grid.addWidget(self.screens_metric, 0, 1)
        grid.addWidget(self.rms_metric, 1, 0)
        grid.addWidget(self.update_metric, 1, 1)
        grid.addWidget(self.display_metric, 2, 0)
        grid.addWidget(self.version_metric, 2, 1)
        layout.addLayout(grid, 6)

        bottom = QGridLayout()
        bottom.setSpacing(10)
        bottom.setColumnStretch(0, 1)
        bottom.setColumnStretch(1, 1)
        self.attention_panel = InfoPanel("Needs Attention")
        self.latest_panel = InfoPanel("Latest Activity")
        bottom.addWidget(self.attention_panel, 0, 0)
        bottom.addWidget(self.latest_panel, 0, 1)
        layout.addLayout(bottom, 2)

        self.tabs.addTab(content, "Overview")

    def build_screens_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(10)

        strip = QHBoxLayout()
        strip.setSpacing(10)
        self.screens_online_metric = MetricCard("Online")
        self.screens_offline_metric = MetricCard("Offline")
        self.screens_update_metric = MetricCard("Updates")
        strip.addWidget(self.screens_online_metric)
        strip.addWidget(self.screens_offline_metric)
        strip.addWidget(self.screens_update_metric)
        layout.addLayout(strip)

        self.device_list = QListWidget()
        self.configure_touch_list(self.device_list)
        layout.addWidget(self.device_list, 1)
        self.tabs.addTab(tab, "Screens")

    def build_activity_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(8)

        hint = QLabel("Newest events first. Use a finger drag anywhere on the list to scroll.")
        hint.setObjectName("Hint")
        layout.addWidget(hint)

        self.activity_list = QListWidget()
        self.configure_touch_list(self.activity_list)
        layout.addWidget(self.activity_list, 1)
        self.tabs.addTab(tab, "Activity")

    def build_updates_tab(self):
        content, layout = self.scrollable_tab()
        layout.setSpacing(10)

        services = QGridLayout()
        services.setSpacing(10)
        self.backend_service_metric = MetricCard("Backend Service")
        self.display_service_metric = MetricCard("Display Service")
        self.update_service_metric = MetricCard("Update Service")
        services.addWidget(self.backend_service_metric, 0, 0)
        services.addWidget(self.display_service_metric, 0, 1)
        services.addWidget(self.update_service_metric, 1, 0, 1, 2)
        layout.addLayout(services)

        self.manager_update_panel = InfoPanel("Manager Pi Update")
        self.github_update_panel = InfoPanel("GitHub Check")
        layout.addWidget(self.manager_update_panel)
        layout.addWidget(self.github_update_panel)

        log_title = QLabel("Manager Update Log")
        log_title.setObjectName("PanelTitle")
        layout.addWidget(log_title)
        self.update_log_list = QListWidget()
        self.configure_touch_list(self.update_log_list)
        self.update_log_list.setMinimumHeight(180)
        layout.addWidget(self.update_log_list, 1)
        self.tabs.addTab(content, "Updates")

    def scrollable_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        enable_touch_scroll(scroll)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 10, 8, 8)
        scroll.setWidget(content)
        return scroll, layout

    def apply_theme(self):
        stylesheet = """
            QMainWindow, QWidget {
                background:#071014;
                color:#eaf5f2;
                font-family:"__UI_FONT__";
            }
            QLabel#Heading {
                color:#ffffff;
                font-size:31px;
                font-weight:900;
            }
            QLabel#Subheading, QLabel#Hint {
                color:#94a9b3;
                font-size:15px;
                font-weight:600;
            }
            QLabel#Clock {
                color:#dff8ec;
                font-size:24px;
                font-weight:900;
            }
            QTabWidget::pane {
                border:0;
                background:transparent;
            }
            QFrame#HeaderDivider {
                background:#c6d3d4;
                min-height:1px;
                max-height:1px;
                border:0;
            }
            QTabBar {
                background:transparent;
                border:0;
            }
            QTabBar::tab {
                background:#132028;
                color:#d8e8e6;
                min-height:52px;
                min-width:100px;
                padding:8px 14px;
                margin-right:5px;
                border-radius:15px;
                font-size:19px;
                font-weight:900;
            }
            QTabBar::tab:selected {
                background:#b9f6ca;
                color:#061014;
            }
            QTabBar::tab:!selected {
                border:1px solid #263943;
            }
            QFrame#HeroPanel {
                background:qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #143224, stop:0.55 #10212a, stop:1 #0d1720);
                border:1px solid #2f4b43;
                border-radius:22px;
            }
            QFrame#InfoPanel {
                background:#101a20;
                border:1px solid #263943;
                border-radius:18px;
            }
            QLabel#HeroTitle {
                color:#ffffff;
                font-size:34px;
                font-weight:900;
            }
            QLabel#HeroDetail {
                color:#b6cacb;
                font-size:20px;
                font-weight:650;
            }
            QLabel#MetricTitle, QLabel#PanelTitle {
                color:#7fdcc0;
                font-size:13px;
                font-weight:900;
                letter-spacing:1px;
            }
            QLabel#MetricValue {
                color:#ffffff;
                font-size:32px;
                font-weight:950;
            }
            QLabel#MetricDetail {
                color:#9eb3bb;
                font-size:17px;
                font-weight:650;
            }
            QLabel#PanelBody {
                color:#e4efed;
                font-size:22px;
                font-weight:750;
            }
            QLabel#RowTitle {
                color:#ffffff;
                font-size:21px;
                font-weight:900;
            }
            QLabel#RowDetail {
                color:#c7d6d8;
                font-size:16px;
                font-weight:700;
            }
            QLabel#RowSmall {
                color:#8fa6b0;
                font-size:14px;
                font-weight:650;
            }
            QLabel#LogText {
                color:#d5e2df;
                font-family:"__MONO_FONT__";
                font-size:13px;
                font-weight:650;
            }
            QListWidget {
                background:transparent;
                border:0;
                outline:0;
            }
            QListWidget::item {
                background:transparent;
                border:0;
                margin:4px 0;
            }
            QListWidget::item:selected {
                background:transparent;
                border:0;
            }
            QScrollArea {
                background:transparent;
                border:0;
            }
            QScrollBar:vertical {
                background:#0b151b;
                width:24px;
                margin:0;
                border-radius:12px;
            }
            QScrollBar::handle:vertical {
                background:#4f6773;
                min-height:48px;
                border-radius:12px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height:0;
            }
            QScrollBar:horizontal {
                height:0;
            }
            """
        self.setStyleSheet(
            stylesheet.replace("__UI_FONT__", self.ui_font).replace("__MONO_FONT__", self.mono_font)
        )

    def configure_touch_list(self, list_widget):
        list_widget.setAlternatingRowColors(False)
        list_widget.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        list_widget.setSpacing(6)
        list_widget.setSelectionMode(QListWidget.NoSelection)
        enable_touch_scroll(list_widget)

    def add_widget_item(self, list_widget, widget, height):
        item = QListWidgetItem()
        item.setFlags(Qt.NoItemFlags)
        item.setSizeHint(QSize(0, height))
        list_widget.addItem(item)
        list_widget.setItemWidget(item, widget)

    def set_empty_row(self, list_widget, text):
        list_widget.clear()
        widget = InfoPanel("Status")
        widget.set_body(text)
        self.add_widget_item(list_widget, widget, 92)

    def fetch_json(self, path, default):
        try:
            response = requests.get(BACKEND_URL + path, timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception as error:
            self.fetch_errors[path] = str(error)
            return default

    def refresh(self):
        self.fetch_errors = {}
        self.clock_label.setText(datetime.now().strftime("%H:%M"))

        addresses = local_addresses()
        if addresses:
            address_text = "  ".join(f"http://{address}:8765" for address in addresses)
            self.subheading.setText(f"PC remote connection: {address_text}")
        else:
            self.subheading.setText("Waiting for network address...")

        manager_status = self.fetch_json("/api/manager/status", {})
        devices = self.fetch_json("/api/devices", [])
        activity = self.fetch_json("/api/activity?limit=40", [])

        update_status = manager_status.get("update_status") if isinstance(manager_status, dict) else {}
        if not isinstance(update_status, dict):
            update_status = self.fetch_json("/api/update-status", {})

        self.populate_overview(manager_status, devices, activity, update_status)
        self.populate_devices(devices, update_status)
        self.populate_activity(activity)
        self.populate_updates(manager_status, update_status)

    def device_counts(self, devices):
        total = len(devices)
        offline = sum(1 for device in devices if clean_text(device.get("state"), "Unknown").lower() == "offline")
        unknown = sum(1 for device in devices if clean_text(device.get("state"), "Unknown").lower() == "unknown")
        online = max(0, total - offline - unknown)
        updates = sum(1 for device in devices if clean_text(device.get("update")).lower().startswith("available"))
        return online, offline, unknown, updates

    def latest_refresh_entry(self, activity):
        return next(
            (
                entry
                for entry in activity
                if entry.get("category") == "Current RMS" and "finished" in clean_text(entry.get("message")).lower()
            ),
            None,
        )

    def populate_overview(self, manager_status, devices, activity, update_status):
        backend_ok = "/api/manager/status" not in self.fetch_errors
        online, offline, unknown, updates = self.device_counts(devices)
        refresh_entry = self.latest_refresh_entry(activity)
        refresh_message = clean_text(refresh_entry.get("message") if refresh_entry else "", "Waiting")
        duration = refresh_duration(refresh_message)

        manager_update_available = bool(update_status.get("manager_update_available"))
        update_tone = "warn" if manager_update_available or updates else "good"
        service_states = {
            "Backend": clean_text(manager_status.get("backend_service"), "unknown"),
            "Display": clean_text(manager_status.get("display_service"), "unknown"),
        }
        problem_service_names = [
            name for name, state in service_states.items() if state.lower() in {"failed", "inactive"}
        ]
        service_problem = bool(problem_service_names)

        if not backend_ok:
            system_title = "Backend connection lost"
            system_detail = "The local status display cannot reach the Manager Pi backend."
            system_tone = "bad"
            system_state = "Offline"
        elif offline or service_problem:
            system_title = "Attention needed"
            parts = []
            if offline:
                parts.append(f"{offline} screen(s) offline")
            if service_problem:
                parts.append("one or more Manager Pi services need attention")
            system_detail = "; ".join(parts)
            system_tone = "warn"
            system_state = "Check"
        elif manager_update_available or updates:
            system_title = "Update available"
            system_detail = "Everything is running, but GitHub has updates waiting."
            system_tone = "warn"
            system_state = "Update"
        else:
            system_title = "System running normally"
            system_detail = "Manager backend is online and display Pis are reporting in."
            system_tone = "good"
            system_state = "Online"

        self.system_title.setText(system_title)
        self.system_detail.setText(system_detail)
        self.system_pill.set_text(system_state, system_tone)

        backend_state = clean_text(manager_status.get("backend_service"), "Online" if backend_ok else "Offline")
        self.backend_metric.set_content(
            backend_state.title(),
            "Local API reachable" if backend_ok else self.fetch_errors.get("/api/manager/status", "No response"),
            "good" if backend_ok and service_tone(backend_state) != "bad" else "bad",
        )
        self.screens_metric.set_content(
            f"{online}/{len(devices)} online",
            f"{offline} offline  |  {unknown} unknown  |  {updates} updates",
            "bad" if offline else "warn" if updates or unknown else "good",
        )
        self.rms_metric.set_content(
            duration or "Waiting",
            refresh_message,
            "good" if duration else "muted",
        )
        self.update_metric.set_content(
            "Available" if manager_update_available or updates else "Current",
            clean_text(update_status.get("message"), "No GitHub check yet."),
            update_tone,
        )
        display_state = clean_text(manager_status.get("display_service"), "unknown")
        self.display_metric.set_content(
            display_state.title(),
            "Touch status display service",
            service_tone(display_state),
        )

        latest_version = clean_text(update_status.get("latest_version"), CURRENT_VERSION)
        self.version_metric.set_content(
            f"v{CURRENT_VERSION}",
            f"GitHub latest: v{latest_version}",
            "warn" if latest_version != CURRENT_VERSION else "good",
        )

        attention = []
        for device in devices:
            state = clean_text(device.get("state"), "Unknown")
            update = clean_text(device.get("update"))
            if state.lower() == "offline":
                attention.append(f"{clean_text(device.get('name') or device.get('id'), 'Screen')}: offline")
            elif update.lower().startswith("available"):
                attention.append(f"{clean_text(device.get('name') or device.get('id'), 'Screen')}: {update}")
        if service_problem:
            attention.append(f"Manager Pi service issue: {', '.join(problem_service_names)}.")
        if not attention:
            attention.append("No urgent issues.")
        self.attention_panel.set_body("\n".join(attention[:5]))

        if activity:
            latest = activity[0]
            self.latest_panel.set_body(
                f"{format_time(latest.get('ts'))}  |  {clean_text(latest.get('category'), 'Log')}\n"
                f"{clean_text(latest.get('message'), 'No message.')}"
            )
        else:
            self.latest_panel.set_body("No activity logged yet.")

    def populate_devices(self, devices, update_status):
        online, offline, unknown, updates = self.device_counts(devices)
        total = len(devices)
        self.screens_online_metric.set_content(str(online), f"{total} registered total", "good" if online else "muted")
        self.screens_offline_metric.set_content(str(offline), f"{unknown} unknown", "bad" if offline else "good")
        self.screens_update_metric.set_content(str(updates), clean_text(update_status.get("message"), "No update check."), "warn" if updates else "good")

        if not devices:
            self.set_empty_row(self.device_list, "No display Pis have registered with this Manager Pi yet.")
            return

        def sort_key(device):
            state = clean_text(device.get("state"), "Unknown").lower()
            update = clean_text(device.get("update")).lower().startswith("available")
            priority = 0 if state == "offline" else 1 if update else 2
            return (priority, clean_text(device.get("name") or device.get("id")).lower())

        self.device_list.clear()
        for device in sorted(devices, key=sort_key):
            self.add_widget_item(self.device_list, DeviceRow(device), 126)

    def populate_activity(self, activity):
        if not activity:
            self.set_empty_row(self.activity_list, "No activity has been logged yet.")
            return

        self.activity_list.clear()
        for entry in activity:
            self.add_widget_item(self.activity_list, ActivityRow(entry), 96)

    def populate_updates(self, manager_status, update_status):
        backend_service = clean_text(manager_status.get("backend_service"), "unknown")
        display_service = clean_text(manager_status.get("display_service"), "unknown")
        update_service = clean_text(manager_status.get("update_service"), "unknown")
        self.backend_service_metric.set_content(backend_service.title(), "warehouse-manager-backend.service", service_tone(backend_service))
        self.display_service_metric.set_content(display_service.title(), "warehouse-manager-display.service", service_tone(display_service))
        self.update_service_metric.set_content(update_service.title(), "warehouse-manager-update.service", service_tone(update_service))

        manager_update = manager_status.get("manager_update_status") if isinstance(manager_status, dict) else {}
        if isinstance(manager_update, dict) and manager_update:
            progress = clean_text(manager_update.get("progress"), "0")
            state = clean_text(manager_update.get("state"), "unknown")
            title = clean_text(manager_update.get("title"), "Manager update")
            detail = clean_text(manager_update.get("detail"))
            updated_at = clean_text(manager_update.get("updated_at"))
            self.manager_update_panel.set_body(f"{progress}%  |  {state.upper()}\n{title}\n{detail}\n{updated_at}")
        else:
            self.manager_update_panel.set_body("No Manager Pi update has run yet.")

        self.github_update_panel.set_body(
            f"Local v{clean_text(update_status.get('local_version'), CURRENT_VERSION)}  |  "
            f"GitHub v{clean_text(update_status.get('latest_version'), CURRENT_VERSION)}\n"
            f"{clean_text(update_status.get('message'), 'No GitHub check yet.')}"
        )

        log_tail = clean_text(manager_status.get("manager_update_log") if isinstance(manager_status, dict) else "")
        self.update_log_list.clear()
        if not log_tail:
            self.add_widget_item(self.update_log_list, LogLine("No update log yet."), 56)
            return
        for line in log_tail.splitlines()[-24:]:
            self.add_widget_item(self.update_log_list, LogLine(line), 54)


def main():
    QApplication.setAttribute(Qt.AA_SynthesizeMouseForUnhandledTouchEvents, True)
    app = QApplication(sys.argv)
    window = ManagerStatusWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

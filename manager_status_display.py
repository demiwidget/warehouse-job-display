import socket
import sys

import requests
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QScroller,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app_version import CURRENT_VERSION
from manager_app.security import security_status


BACKEND_URL = "http://127.0.0.1:8765"


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


class StatusCard(QLabel):
    def __init__(self, title):
        super().__init__()
        self.title = title
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setMinimumHeight(78)
        self.setStyleSheet(
            "background:#15181b; border:1px solid #29323a; border-radius:14px; "
            "padding:10px; font-size:18px; font-weight:700; color:#e8f1f2;"
        )
        self.set_value("Waiting")

    def set_value(self, value):
        self.setText(f"<div style='color:#6bdcff;font-size:14px'>{self.title}</div><div>{value}</div>")


class ManagerStatusWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Warehouse Manager Pi Status")
        self.resize(800, 480)

        root_widget = QWidget()
        root = QVBoxLayout(root_widget)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(10)

        heading = QLabel("Warehouse Manager Pi")
        heading.setStyleSheet("font-size:30px; font-weight:800; color:#ffffff;")
        root.addWidget(heading)

        subheading = QLabel("")
        subheading.setObjectName("subheading")
        subheading.setWordWrap(True)
        subheading.setStyleSheet("font-size:18px; color:#a9b8c0;")
        self.subheading = subheading
        root.addWidget(subheading)

        tabs = QTabWidget()
        tabs.setTabPosition(QTabWidget.North)
        tabs.setDocumentMode(True)
        root.addWidget(tabs, 1)

        overview_tab = QWidget()
        overview = QVBoxLayout(overview_tab)
        overview.setContentsMargins(8, 10, 8, 8)
        overview.setSpacing(10)

        cards = QGridLayout()
        cards.setSpacing(10)
        self.backend_card = StatusCard("Backend")
        self.refresh_card = StatusCard("Current RMS")
        self.devices_card = StatusCard("Display Pis")
        self.version_card = StatusCard("Version")
        self.security_card = StatusCard("Security")
        cards.addWidget(self.backend_card, 0, 0)
        cards.addWidget(self.refresh_card, 0, 1)
        cards.addWidget(self.devices_card, 1, 0)
        cards.addWidget(self.version_card, 1, 1)
        cards.addWidget(self.security_card, 2, 0, 1, 2)
        overview.addLayout(cards)

        self.footer = QLabel("")
        self.footer.setWordWrap(True)
        self.footer.setStyleSheet("font-size:14px; color:#8ea0aa;")
        overview.addWidget(self.footer)
        overview.addStretch(1)
        tabs.addTab(overview_tab, "Overview")

        device_tab = QWidget()
        device_layout = QVBoxLayout(device_tab)
        device_layout.setContentsMargins(8, 10, 8, 8)
        self.device_list = QListWidget()
        self.configure_touch_list(self.device_list)
        device_layout.addWidget(self.device_list)
        tabs.addTab(device_tab, "Screens")

        activity_tab = QWidget()
        activity_layout = QVBoxLayout(activity_tab)
        activity_layout.setContentsMargins(8, 10, 8, 8)
        self.activity_list = QListWidget()
        self.configure_touch_list(self.activity_list)
        activity_layout.addWidget(self.activity_list)
        tabs.addTab(activity_tab, "Log")

        self.setCentralWidget(root_widget)
        self.apply_theme()
        self.showFullScreen()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(3000)
        self.refresh()

    def apply_theme(self):
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background:#0c1014; color:#e8f1f2; font-family: Arial; }
            QTabWidget::pane { border:1px solid #26313a; border-radius:10px; background:#0f151b; }
            QTabBar::tab {
                background:#18222b; color:#d9e7eb; min-height:54px; min-width:144px;
                padding:10px 18px; margin-right:6px; border-top-left-radius:12px; border-top-right-radius:12px;
                font-size:21px; font-weight:800;
            }
            QTabBar::tab:selected { background:#2a3b47; color:#ffffff; }
            QListWidget { background:#0f151b; border:0; color:#e8f1f2; font-size:20px; }
            QListWidget::item {
                background:#14202a; color:#e8f1f2; border:1px solid #263746;
                border-radius:12px; margin:6px 2px; padding:12px;
            }
            QListWidget::item:alternate { background:#182734; color:#e8f1f2; }
            QListWidget::item:selected { background:#25475a; color:#ffffff; }
            QScrollBar:vertical { background:#0b1116; width:28px; margin:0; border-radius:14px; }
            QScrollBar::handle:vertical { background:#4b6475; min-height:50px; border-radius:14px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
            """
        )

    def configure_touch_list(self, list_widget):
        list_widget.setAlternatingRowColors(True)
        list_widget.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        list_widget.setSpacing(2)
        QScroller.grabGesture(list_widget.viewport(), QScroller.TouchGesture)

    def set_list_rows(self, list_widget, rows):
        list_widget.clear()
        if not rows:
            item = QListWidgetItem("No entries yet.")
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            item.setSizeHint(item.sizeHint().expandedTo(item.sizeHint()))
            list_widget.addItem(item)
            return

        for row in rows:
            item = QListWidgetItem(row)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            list_widget.addItem(item)

    def fetch_json(self, path, default):
        try:
            response = requests.get(BACKEND_URL + path, timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception:
            return default

    def refresh(self):
        addresses = local_addresses()
        if addresses:
            address_text = ", ".join(f"http://{address}:8765" for address in addresses)
            self.subheading.setText(f"Connect the PC remote app to: {address_text}")
        else:
            self.subheading.setText("Waiting for network address...")

        devices = self.fetch_json("/api/devices", [])
        activity = self.fetch_json("/api/activity?limit=20", [])
        update_status = self.fetch_json("/api/update-status", {})

        online = sum(1 for device in devices if str(device.get("state", "")) != "Offline")
        offline = max(0, len(devices) - online)
        self.backend_card.set_value("Online")
        self.devices_card.set_value(f"{online} online / {offline} offline")
        self.version_card.set_value(f"v{CURRENT_VERSION}")
        status = security_status()
        if status.get("legacy_code_active"):
            self.security_card.set_value("Legacy password active - change it in the PC app")
        elif status.get("password_set"):
            self.security_card.set_value("Password protected")
        else:
            self.security_card.set_value("Password setup pending")
        latest_refresh = next(
            (entry for entry in activity if entry.get("category") == "Current RMS" and "finished" in entry.get("message", "")),
            None,
        )
        self.refresh_card.set_value(latest_refresh.get("message", "Waiting") if latest_refresh else "Waiting")
        self.footer.setText(str(update_status.get("message") or "Update status not checked yet."))

        self.populate_devices(devices)
        self.populate_activity(activity)

    def populate_devices(self, devices):
        rows = []
        for device in devices:
            name = str(device.get("name") or device.get("id") or "Unnamed screen")
            state = str(device.get("state") or "Unknown")
            screen = str(device.get("screen") or "unknown")
            ip = str(device.get("ip") or "no IP")
            version = str(device.get("version") or "unknown version")
            rows.append(f"{name}  |  {state}\n{ip}  |  {screen}  |  v{version}")
        self.set_list_rows(self.device_list, rows)

    def populate_activity(self, activity):
        rows = []
        for entry in activity:
            ts = str(entry.get("ts") or "")
            level = str(entry.get("level") or "info").upper()
            category = str(entry.get("category") or "Log")
            message = str(entry.get("message") or "")
            rows.append(f"{level}  |  {category}\n{ts}\n{message}")
        self.set_list_rows(self.activity_list, rows)


def main():
    app = QApplication(sys.argv)
    window = ManagerStatusWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

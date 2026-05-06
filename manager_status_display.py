import socket
import sys

import requests
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_version import CURRENT_VERSION


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
        self.setMinimumHeight(90)
        self.setStyleSheet(
            "background:#15181b; border:1px solid #29323a; border-radius:14px; "
            "padding:14px; font-size:22px; font-weight:700; color:#e8f1f2;"
        )
        self.set_value("Waiting")

    def set_value(self, value):
        self.setText(f"<div style='color:#6bdcff;font-size:16px'>{self.title}</div><div>{value}</div>")


class ManagerStatusWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Warehouse Manager Pi Status")
        self.resize(1600, 900)

        root_widget = QWidget()
        root = QVBoxLayout(root_widget)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(18)

        heading = QLabel("Warehouse Manager Pi")
        heading.setStyleSheet("font-size:42px; font-weight:800; color:#ffffff;")
        root.addWidget(heading)

        subheading = QLabel("")
        subheading.setObjectName("subheading")
        subheading.setStyleSheet("font-size:18px; color:#a9b8c0;")
        self.subheading = subheading
        root.addWidget(subheading)

        cards = QGridLayout()
        self.backend_card = StatusCard("Backend")
        self.refresh_card = StatusCard("Current RMS")
        self.devices_card = StatusCard("Display Pis")
        self.version_card = StatusCard("Version")
        cards.addWidget(self.backend_card, 0, 0)
        cards.addWidget(self.refresh_card, 0, 1)
        cards.addWidget(self.devices_card, 0, 2)
        cards.addWidget(self.version_card, 0, 3)
        root.addLayout(cards)

        tables = QHBoxLayout()
        self.device_table = QTableWidget(0, 5)
        self.device_table.setHorizontalHeaderLabels(["Name", "IP", "Screen", "Version", "State"])
        self.activity_table = QTableWidget(0, 4)
        self.activity_table.setHorizontalHeaderLabels(["Time", "Level", "Category", "Message"])
        tables.addWidget(self.device_table, 1)
        tables.addWidget(self.activity_table, 2)
        root.addLayout(tables, 1)

        self.footer = QLabel("")
        self.footer.setStyleSheet("font-size:16px; color:#8ea0aa;")
        root.addWidget(self.footer)

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
            QTableWidget { background:#111820; color:#e8f1f2; gridline-color:#26313a; font-size:16px; }
            QHeaderView::section { background:#1f2a33; color:#ffffff; padding:8px; border:0; font-weight:700; }
            """
        )

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
        latest_refresh = next(
            (entry for entry in activity if entry.get("category") == "Current RMS" and "finished" in entry.get("message", "")),
            None,
        )
        self.refresh_card.set_value(latest_refresh.get("message", "Waiting") if latest_refresh else "Waiting")
        self.footer.setText(str(update_status.get("message") or "Update status not checked yet."))

        self.populate_devices(devices)
        self.populate_activity(activity)

    def populate_devices(self, devices):
        self.device_table.setRowCount(len(devices))
        for row, device in enumerate(devices):
            values = [
                device.get("name", ""),
                device.get("ip", ""),
                device.get("screen", ""),
                device.get("version", ""),
                device.get("state", ""),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if column == 4:
                    if str(value) == "Offline":
                        item.setBackground(QColor("#8a3b3b"))
                    else:
                        item.setBackground(QColor("#2f6f4e"))
                self.device_table.setItem(row, column, item)
        self.device_table.resizeColumnsToContents()

    def populate_activity(self, activity):
        self.activity_table.setRowCount(len(activity))
        for row, entry in enumerate(activity):
            values = [
                entry.get("ts", ""),
                str(entry.get("level", "")).upper(),
                entry.get("category", ""),
                entry.get("message", ""),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if column == 1 and str(value).lower() == "error":
                    item.setBackground(QColor("#9b2226"))
                elif column == 1 and str(value).lower() == "warning":
                    item.setBackground(QColor("#bb7f16"))
                self.activity_table.setItem(row, column, item)
        self.activity_table.resizeColumnsToContents()
        if self.activity_table.columnCount() >= 4:
            self.activity_table.setColumnWidth(3, 760)


def main():
    app = QApplication(sys.argv)
    window = ManagerStatusWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

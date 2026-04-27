import json
import sys
from pathlib import Path

import requests
from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
    QHeaderView,
    QDialog,
    QPushButton,
)

try:
    from PySide6.QtMultimedia import QSoundEffect
except Exception:
    QSoundEffect = None

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "viewer_config.json"

DEFAULT_CONFIG = {
    "server": "http://MANAGER_PC_IP:8765",
    "device_id": "pi-1",
    "device_name": "Warehouse Screen 1",
    "version": "2.0.1",
    "screen": "today",
    "allow_all_screens": True,
}


class DashboardTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.row_payloads = []
        self.headers_for_data = []
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(42)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.horizontalHeader().setStretchLastSection(False)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.horizontalHeader().setMinimumSectionSize(90)

    def set_rows(self, headers, rows):
        self.clear()
        self.headers_for_data = headers
        self.row_payloads = rows
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setRowCount(len(rows))

        for row_index, row in enumerate(rows):
            row_color = row.get("__row_color")
            for column_index, header in enumerate(headers):
                value = row.get(header, "")
                item = QTableWidgetItem(str(value))
                if row_color:
                    item.setBackground(QColor(row_color))
                self.setItem(row_index, column_index, item)

        self.resizeColumnsToContents()
        if headers:
            self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        if len(headers) > 4:
            self.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)

    def row_data(self, row):
        if 0 <= row < len(self.row_payloads):
            return self.row_payloads[row]
        return {}


class CombinedJobsPage(QWidget):
    def __init__(self, title_out, title_in):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        self.out_label = QLabel(title_out)
        self.out_label.setObjectName("sectionHeading")
        self.out_table = DashboardTable()
        self.in_label = QLabel(title_in)
        self.in_label.setObjectName("sectionHeading")
        self.in_table = DashboardTable()

        layout.addWidget(self.out_label)
        layout.addWidget(self.out_table, 1)
        layout.addWidget(self.in_label)
        layout.addWidget(self.in_table, 1)


class UnpreppedItemsDialog(QDialog):
    def __init__(self, job_name, job_number, items, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Unprepped Items - {job_name}")
        self.resize(1000, 650)

        layout = QVBoxLayout(self)
        heading = QLabel(f"<h2>{job_name} <span style='font-weight:400'>(#{job_number})</span></h2>")
        sub = QLabel("Items below are not yet fully prepared.")
        table = DashboardTable()
        table.set_rows(["Item", "Code", "Prepared", "Total", "Remaining", "Status"], items)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)

        layout.addWidget(heading)
        layout.addWidget(sub)
        layout.addWidget(table, 1)
        layout.addWidget(close_btn)


class AlertDialog(QDialog):
    def __init__(self, title, html, parent=None):
        super().__init__(parent)
        self.acknowledged = False
        self.setWindowTitle(title or "Notification")
        self.resize(1200, 760)
        self.setModal(True)
        flags = self.windowFlags()
        flags |= Qt.WindowStaysOnTopHint
        flags &= ~Qt.WindowCloseButtonHint
        self.setWindowFlags(flags)

        layout = QVBoxLayout(self)
        heading = QLabel(f"<h1>{title or 'Notification'}</h1>")
        body = QTextBrowser()
        body.setHtml(html or "")
        body.setOpenExternalLinks(True)
        close_btn = QPushButton("Confirm Notification")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.confirm_notification)

        layout.addWidget(heading)
        layout.addWidget(body, 1)
        layout.addWidget(close_btn)

    def confirm_notification(self):
        self.acknowledged = True
        self.accept()

    def reject(self):
        # Notification popups require an explicit acknowledgement.
        return

    def closeEvent(self, event):
        if self.acknowledged:
            event.accept()
            return
        event.ignore()


class SummaryCard(QWidget):
    def __init__(self, title, accent="#5bc0eb"):
        super().__init__()
        layout = QVBoxLayout(self)

        self.title = QLabel(title)
        self.title.setStyleSheet(f"font-size:16px; font-weight:700; color:{accent};")
        self.value = QLabel("0")
        self.value.setAlignment(Qt.AlignCenter)
        self.value.setStyleSheet("font-size:34px; font-weight:700; padding:8px;")
        self.caption = QLabel("")
        self.caption.setAlignment(Qt.AlignCenter)
        self.caption.setStyleSheet("font-size:13px; color:#bbb;")
        self.caption.setWordWrap(True)

        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.caption)
        self.setStyleSheet("background:#15181b; border:1px solid #22282e; border-radius:12px; padding:8px;")

    def set_data(self, value, caption=""):
        self.value.setText(str(value))
        self.caption.setText(caption)


def load_config():
    cfg = DEFAULT_CONFIG.copy()
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    else:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


class ViewerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.current_screen = self.config.get("screen", "today")
        self.pending_alerts = []
        self.active_alert_dialog = None
        self.sound_effect = QSoundEffect(self) if QSoundEffect else None
        self.setWindowTitle(self.config.get("device_name", "Warehouse Viewer"))
        self.resize(1600, 900)
        self.build_ui()
        self.apply_theme()
        self.showFullScreen()

        self.register_timer = QTimer(self)
        self.register_timer.timeout.connect(self.register)
        self.register_timer.start(10000)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_all)
        self.refresh_timer.start(3000)

        self.alert_timer = QTimer(self)
        self.alert_timer.timeout.connect(self.poll_alerts)
        self.alert_timer.start(2500)

        self.set_current_tab()
        self.register()
        self.refresh_all()

    def build_ui(self):
        from PySide6.QtWidgets import QGridLayout

        central = QWidget()
        root = QVBoxLayout(central)

        cards = QGridLayout()
        self.card_today_out = SummaryCard("Today Out")
        self.card_today_in = SummaryCard("Today In", "#9bc53d")
        self.card_tomorrow_out = SummaryCard("Tomorrow Out", "#fde74c")
        self.card_tomorrow_in = SummaryCard("Tomorrow In", "#e55934")
        self.card_prep = SummaryCard("Prep", "#5bc0eb")
        self.card_outstanding = SummaryCard("Outstanding", "#c3423f")
        cards.addWidget(self.card_today_out, 0, 0)
        cards.addWidget(self.card_today_in, 0, 1)
        cards.addWidget(self.card_tomorrow_out, 0, 2)
        cards.addWidget(self.card_tomorrow_in, 0, 3)
        cards.addWidget(self.card_prep, 1, 0, 1, 2)
        cards.addWidget(self.card_outstanding, 1, 2, 1, 2)
        root.addLayout(cards)

        self.tabs = QTabWidget()
        self.today_page = CombinedJobsPage("Jobs Collecting / Delivering Today", "Jobs Returning Today")
        self.tomorrow_page = CombinedJobsPage("Jobs Collecting / Delivering Tomorrow", "Jobs Returning Tomorrow")
        self.prep_table = DashboardTable()
        self.outstanding_table = DashboardTable()
        self.notifications_table = DashboardTable()

        self.tabs.addTab(self.today_page, "Today")
        self.tabs.addTab(self.tomorrow_page, "Tomorrow")
        self.tabs.addTab(self.prep_table, "Prep Status")
        self.tabs.addTab(self.outstanding_table, "Outstanding Items")
        self.tabs.addTab(self.notifications_table, "Notification History")
        self.prep_table.cellDoubleClicked.connect(self.open_unprepped_items_dialog)

        root.addWidget(self.tabs)
        self.setCentralWidget(central)

        status = QStatusBar()
        self.setStatusBar(status)
        self.version_label = QLabel(f"v{self.config.get('version', 'unknown')}")
        self.last_refresh = QLabel("Last refresh: never")
        status.addPermanentWidget(self.version_label)
        status.addPermanentWidget(self.last_refresh)

        menubar = self.menuBar()
        view_menu = menubar.addMenu("View")
        refresh_action = QAction("Refresh now", self)
        refresh_action.triggered.connect(self.refresh_all)
        fullscreen_action = QAction("Toggle fullscreen", self)
        fullscreen_action.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(refresh_action)
        view_menu.addAction(fullscreen_action)

    def apply_theme(self):
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background-color: #111315; color: #f3f3f3; font-size: 14px; }
            QTableWidget { background-color: #171a1d; gridline-color: #2a2f35; alternate-background-color: #1d2126; border: 1px solid #2a2f35; border-radius: 12px; font-size: 16px; selection-background-color: #27445d; }
            QTableWidget::item { padding: 10px; height: 34px; }
            QHeaderView::section { background-color: #1f252b; color: #f3f3f3; padding: 10px; border: none; border-bottom: 1px solid #2a2f35; font-size: 15px; font-weight: 600; }
            QTabWidget::pane { border: 1px solid #2a2f35; border-radius: 14px; }
            QTabBar::tab { background: #1a1f24; color: #dcdcdc; padding: 12px 20px; border-top-left-radius: 10px; border-top-right-radius: 10px; }
            QTabBar::tab:selected { background: #2b343d; }
            QPushButton { background-color: #2b343d; color: white; padding: 10px 14px; border-radius: 10px; }
            QPushButton:hover { background-color: #36424d; }
            QLabel { color: #f3f3f3; }
            QLabel#sectionHeading { font-size: 22px; font-weight: 700; padding: 8px 4px; }
            QStatusBar { background-color: #15181b; }
            QTextBrowser { background-color: #171a1d; border: 1px solid #2a2f35; border-radius: 12px; padding: 16px; font-size: 18px; }
            """
        )

    def server_url(self, path):
        return self.config["server"].rstrip("/") + path

    def save_config(self):
        CONFIG_PATH.write_text(json.dumps(self.config, indent=2), encoding="utf-8")

    def register(self):
        try:
            requests.post(
                self.server_url("/register"),
                json={
                    "id": self.config["device_id"],
                    "name": self.config["device_name"],
                    "screen": self.current_screen,
                    "version": self.config["version"],
                },
                timeout=5,
            )
        except Exception:
            pass

    def set_current_tab(self):
        mapping = {"today": 0, "tomorrow": 1, "prep": 2, "outstanding": 3, "notifications": 4}
        if self.current_screen in mapping:
            self.tabs.setCurrentIndex(mapping[self.current_screen])

    def poll_alerts(self):
        try:
            alert = requests.get(self.server_url(f"/alerts/{self.config['device_id']}"), timeout=5).json()
            if not alert:
                return
            self.pending_alerts.append(alert)
            self.show_next_alert()
        except Exception:
            pass

    def show_next_alert(self):
        if self.active_alert_dialog or not self.pending_alerts:
            return

        alert = self.pending_alerts.pop(0)
        if alert.get("play_sound"):
            self.play_alert_sound(alert.get("sound", ""))

        if not alert.get("show_popup", True):
            QTimer.singleShot(0, self.finish_current_alert)
            return

        self.active_alert_dialog = AlertDialog(alert.get("title", "Notification"), alert.get("html", ""), self)
        self.active_alert_dialog.finished.connect(self.finish_current_alert)
        self.active_alert_dialog.open()

    def finish_current_alert(self, *_args):
        self.active_alert_dialog = None
        self.show_next_alert()

    def play_alert_sound(self, sound_name):
        sound_path = BASE_DIR / "sounds" / str(sound_name or "").strip()
        if self.sound_effect and sound_path.exists():
            self.sound_effect.stop()
            self.sound_effect.setSource(QUrl.fromLocalFile(str(sound_path)))
            self.sound_effect.setLoopCount(1)
            self.sound_effect.setVolume(0.9)
            self.sound_effect.play()
            return
        QApplication.beep()

    def fetch_screen(self, name):
        try:
            return requests.get(self.server_url(f"/screen/{name}"), timeout=10).json()
        except Exception:
            return {"title": name.title(), "summary": {}, "rows": []}

    def refresh_all(self):
        today = self.fetch_screen("today")
        tomorrow = self.fetch_screen("tomorrow")
        prep = self.fetch_screen("prep")
        outstanding = self.fetch_screen("outstanding")
        notifications = self.fetch_screen("notifications")

        self.card_today_out.set_data(today.get("summary", {}).get("Jobs Out", 0), "Jobs collecting / delivering today")
        self.card_today_in.set_data(today.get("summary", {}).get("Jobs In", 0), "Jobs returning today")
        self.card_tomorrow_out.set_data(
            tomorrow.get("summary", {}).get("Jobs Out", 0),
            "Jobs collecting / delivering tomorrow",
        )
        self.card_tomorrow_in.set_data(tomorrow.get("summary", {}).get("Jobs In", 0), "Jobs returning tomorrow")

        prepared_qty = int(prep.get("summary", {}).get("Prepared Qty", 0) or 0)
        remaining_qty = int(prep.get("summary", {}).get("Remaining Qty", 0) or 0)
        total_qty = prepared_qty + remaining_qty
        if total_qty > 0:
            prepped_pct = round((prepared_qty / total_qty) * 100)
            unprepped_pct = round((remaining_qty / total_qty) * 100)
        else:
            prepped_pct = 0
            unprepped_pct = 0

        self.card_prep.set_data(
            f"{prepared_qty}/{total_qty}",
            f"{prepped_pct}% prepped / {unprepped_pct}% unprepped",
        )
        self.card_outstanding.set_data(
            outstanding.get("summary", {}).get("Outstanding", 0),
            "Booked out items still awaiting check-in",
        )

        today_out = today.get("out_rows", [])
        today_in = today.get("in_rows", [])
        tomorrow_out = tomorrow.get("out_rows", [])
        tomorrow_in = tomorrow.get("in_rows", [])

        self.today_page.out_table.set_rows(
            ["Job Name", "Job Number", "Customer collecting", "Time", "Client", "Owner", "Booked Out"],
            today_out,
        )
        self.today_page.in_table.set_rows(
            ["Job Name", "Job Number", "Customer Returning", "Time", "Client", "Owner", "Job Returned"],
            today_in,
        )
        self.tomorrow_page.out_table.set_rows(
            ["Job Name", "Job Number", "Customer collecting", "Time", "Client", "Owner"],
            tomorrow_out,
        )
        self.tomorrow_page.in_table.set_rows(
            ["Job Name", "Job Number", "Customer Returning", "Time", "Client", "Owner", "Job Returned"],
            tomorrow_in,
        )
        self.prep_table.set_rows(
            ["Job Name", "Job Number", "Delivery Date", "Prep Status", "Owner"],
            prep.get("rows", []),
        )
        self.outstanding_table.set_rows(
            ["Job Number", "Job Name", "Booked Out", "Checked In", "Total Items", "Owner"],
            outstanding.get("rows", []),
        )
        self.notifications_table.set_rows(
            ["Time", "Title", "Source", "Details"],
            notifications.get("rows", []),
        )
        self.last_refresh.setText(
            "Last refresh: " + __import__("datetime").datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        )

    def open_unprepped_items_dialog(self, row, _column):
        data = self.prep_table.row_data(row)
        items = data.get("__unprepped_items", [])
        if not items:
            QMessageBox.information(self, "Prep Status", "Everything on this job is prepared.")
            return
        dlg = UnpreppedItemsDialog(data.get("Job Name", "Job"), data.get("Job Number", ""), items, self)
        dlg.exec()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = ViewerWindow()
    win.show()
    sys.exit(app.exec())

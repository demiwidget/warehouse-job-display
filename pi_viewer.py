import json
import os
import shutil
import subprocess
import sys
from tempfile import NamedTemporaryFile
import time
from pathlib import Path
from threading import Thread

os.environ.setdefault("QT_IM_MODULE", "none")
os.environ.setdefault("QT_VIRTUALKEYBOARD_DESKTOP_DISABLE", "1")

import requests
from PySide6.QtCore import QTimer, Qt, QUrl, Signal
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
    QHBoxLayout,
    QDialog,
    QPushButton,
    QScroller,
)

try:
    from PySide6.QtMultimedia import QSoundEffect
except Exception:
    QSoundEffect = None

try:
    import fcntl
except Exception:
    fcntl = None

from app_version import CURRENT_VERSION, sync_config_version
from pi_audio import apply_audio_preferences, sync_audio_config
from pi_identity import registration_id, registration_payload
from pi_status import post_status

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "viewer_config.json"
LOCK_PATH = Path("/tmp/warehouse-dashboard-viewer.lock")
VIEWER_LOCK_HANDLE = None

DEFAULT_CONFIG = {
    "server": "http://MANAGER_PC_IP:8765",
    "device_id": "pi-1",
    "device_name": "Warehouse Screen 1",
    "version": CURRENT_VERSION,
    "screen": "today",
    "allow_all_screens": True,
    "audio_output": "hdmi",
    "audio_volume": 100,
}


def write_json_atomic(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        Path(temp_name).replace(path)
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except Exception:
                pass


def enable_click_drag_scroll(widget):
    """Allow touch and mouse-drag scrolling on scrollable Qt widgets."""
    viewport = widget.viewport() if hasattr(widget, "viewport") else widget
    viewport.setAttribute(Qt.WA_AcceptTouchEvents, True)
    QScroller.grabGesture(viewport, QScroller.TouchGesture)
    QScroller.grabGesture(viewport, QScroller.LeftMouseButtonGesture)


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
        self.setVerticalScrollMode(QTableWidget.ScrollPerPixel)
        self.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        self.setAutoScroll(False)
        enable_click_drag_scroll(self)

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

    def set_touch_row_height(self, height):
        self.verticalHeader().setDefaultSectionSize(height)
        for row in range(self.rowCount()):
            self.setRowHeight(row, height)

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
        table.set_rows(["Item", "Code", "Prepared", "Total", "Unprepped", "Status", "Reserved Detail"], items)
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
        enable_click_drag_scroll(body)
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
    changed = False
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    changed = sync_config_version(cfg) or changed
    changed = sync_audio_config(cfg) or changed
    cfg, identity_changed, _payload = registration_payload(cfg)
    changed = changed or identity_changed
    if changed or not CONFIG_PATH.exists():
        write_json_atomic(CONFIG_PATH, cfg)
    return cfg


def acquire_viewer_lock():
    global VIEWER_LOCK_HANDLE
    if fcntl is None:
        return True

    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    handle = open(LOCK_PATH, "a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False

    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    VIEWER_LOCK_HANDLE = handle
    return True


class ViewerWindow(QMainWindow):
    refresh_result_ready = Signal(object)
    alert_result_ready = Signal(object)

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.current_screen = self.config.get("screen", "today")
        self.pending_alerts = []
        self.remote_alert_queue_remaining = 0
        self.active_alert_dialog = None
        self.sound_effect = QSoundEffect(self) if QSoundEffect else None
        self.sound_process = None
        self.last_audio_apply_at = 0.0
        self.refresh_in_progress = False
        self.refresh_queued = False
        self.alert_poll_in_progress = False
        self.register_in_progress = False
        self.setWindowTitle(self.config.get("device_name", "Warehouse Viewer"))
        self.resize(1600, 900)
        self.build_ui()
        self.apply_theme()
        self.showFullScreen()
        self.refresh_result_ready.connect(self.handle_refresh_result)
        self.alert_result_ready.connect(self.handle_alert_result)

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
        QTimer.singleShot(800, self.ensure_audio_preferences)
        QTimer.singleShot(5000, self.ensure_audio_preferences)
        QTimer.singleShot(1200, self.report_online_status)

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

        alert_bar = QHBoxLayout()
        alert_bar.addStretch(1)
        self.alert_queue_badge = QLabel("")
        self.alert_queue_badge.setObjectName("alertQueueBadge")
        self.alert_queue_badge.hide()
        alert_bar.addWidget(self.alert_queue_badge)
        root.addLayout(alert_bar)

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
            QPushButton#prepActionButton {
                background-color: #f4c542;
                color: #111315;
                font-size: 18px;
                font-weight: 800;
                padding: 14px 18px;
                border: 2px solid #fff0a6;
                border-radius: 8px;
            }
            QPushButton#prepActionButton:disabled {
                background-color: #343a40;
                color: #8e979f;
                border: 1px solid #4a525a;
            }
            QLabel { color: #f3f3f3; }
            QLabel#sectionHeading { font-size: 22px; font-weight: 700; padding: 8px 4px; }
            QLabel#alertQueueBadge {
                background-color: #c3423f;
                color: white;
                font-size: 15px;
                font-weight: 700;
                padding: 8px 14px;
                border-radius: 14px;
            }
            QStatusBar { background-color: #15181b; }
            QTextBrowser { background-color: #171a1d; border: 1px solid #2a2f35; border-radius: 12px; padding: 16px; font-size: 18px; }
            """
        )

    def server_url(self, path):
        return self.config["server"].rstrip("/") + path

    def save_config(self):
        write_json_atomic(CONFIG_PATH, self.config)

    def register(self):
        if self.register_in_progress:
            return
        self.register_in_progress = True
        Thread(target=self._register_worker, daemon=True).start()

    def _register_worker(self):
        try:
            _cfg, _changed, payload = registration_payload(dict(self.config), screen=self.current_screen)
            requests.post(
                self.server_url("/register"),
                json=payload,
                timeout=5,
            )
        except Exception:
            pass
        finally:
            self.register_in_progress = False

    def report_online_status(self):
        Thread(target=self._report_online_status_worker, daemon=True).start()

    def _report_online_status_worker(self):
        screen_name = str(self.current_screen or "today").replace("_", " ").title()
        try:
            post_status(
                self.config,
                "online",
                f"Display app online on {screen_name}.",
                source="viewer",
                timeout=4,
                screen=self.current_screen,
            )
        except Exception:
            pass

    def set_current_tab(self):
        mapping = {"today": 0, "tomorrow": 1, "prep": 2, "outstanding": 3, "notifications": 4}
        if self.current_screen in mapping:
            self.tabs.setCurrentIndex(mapping[self.current_screen])

    def poll_alerts(self):
        if self.alert_poll_in_progress:
            return
        self.alert_poll_in_progress = True
        Thread(target=self._poll_alert_worker, daemon=True).start()

    def _poll_alert_worker(self):
        result = {"ok": False, "alert": None}
        try:
            response = requests.get(self.server_url(f"/alerts/{registration_id(self.config)}"), timeout=5)
            response.raise_for_status()
            result = {"ok": True, "alert": response.json()}
        except Exception:
            result = {"ok": False, "alert": None}
        self.alert_result_ready.emit(result)

    def handle_alert_result(self, result):
        self.alert_poll_in_progress = False
        if not result.get("ok"):
            return

        alert = result.get("alert")
        if not alert:
            self.remote_alert_queue_remaining = 0
            self.update_notification_queue_badge()
            return
        try:
            self.remote_alert_queue_remaining = max(0, int(alert.get("queue_remaining", 0) or 0))
        except Exception:
            self.remote_alert_queue_remaining = 0
        if alert.get("play_sound"):
            self.play_alert_sound(alert.get("sound", ""))
            alert["_sound_played"] = True
        self.pending_alerts.append(alert)
        self.update_notification_queue_badge()
        self.show_next_alert()

    def show_next_alert(self):
        if self.active_alert_dialog or not self.pending_alerts:
            return

        alert = self.pending_alerts.pop(0)
        self.update_notification_queue_badge()
        if alert.get("play_sound") and not alert.get("_sound_played"):
            self.play_alert_sound(alert.get("sound", ""))

        if not alert.get("show_popup", True):
            QTimer.singleShot(0, self.finish_current_alert)
            return

        self.active_alert_dialog = AlertDialog(alert.get("title", "Notification"), alert.get("html", ""), self)
        self.active_alert_dialog.finished.connect(self.finish_current_alert)
        self.active_alert_dialog.open()

    def finish_current_alert(self, *_args):
        self.active_alert_dialog = None
        self.update_notification_queue_badge()
        self.show_next_alert()

    def update_notification_queue_badge(self):
        queued_count = len(self.pending_alerts) + max(0, self.remote_alert_queue_remaining)
        if queued_count <= 0:
            self.alert_queue_badge.hide()
            self.alert_queue_badge.setText("")
            return
        label = "notification" if queued_count == 1 else "notifications"
        self.alert_queue_badge.setText(f"{queued_count} queued {label}")
        self.alert_queue_badge.show()

    def play_alert_sound(self, sound_name):
        self.ensure_audio_preferences()
        sound_path = BASE_DIR / "sounds" / str(sound_name or "").strip()
        if not sound_path.exists():
            QApplication.beep()
            return

        if self.play_alert_sound_with_system_player(sound_path):
            return

        if self.sound_effect:
            self.sound_effect.stop()
            self.sound_effect.setSource(QUrl.fromLocalFile(str(sound_path)))
            self.sound_effect.setLoopCount(1)
            self.sound_effect.setVolume(0.9)
            self.sound_effect.play()
            return
        QApplication.beep()

    def play_alert_sound_with_system_player(self, sound_path):
        players = [
            ("pw-play", ["pw-play", str(sound_path)]),
            ("paplay", ["paplay", str(sound_path)]),
            ("aplay", ["aplay", "-q", str(sound_path)]),
        ]

        for binary, command in players:
            if not shutil.which(binary):
                continue
            try:
                if self.sound_process and self.sound_process.poll() is None:
                    self.sound_process.terminate()
                self.sound_process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                try:
                    return_code = self.sound_process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    return True
                if return_code == 0:
                    return True
            except Exception:
                continue
        return False

    def ensure_audio_preferences(self, force=False):
        now = time.monotonic()
        if not force and (now - self.last_audio_apply_at) < 20:
            return
        ok, _message = apply_audio_preferences(self.config)
        if ok:
            self.last_audio_apply_at = now

    def fetch_screen_bundle(self):
        try:
            response = requests.get(self.server_url("/screens"), timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception:
            return {}

    def refresh_all(self):
        if self.refresh_in_progress:
            self.refresh_queued = True
            return
        self.refresh_in_progress = True
        Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self):
        bundle = self.fetch_screen_bundle()
        self.refresh_result_ready.emit(
            {
                "ok": bool(bundle),
                "bundle": bundle,
            }
        )

    def handle_refresh_result(self, result):
        self.refresh_in_progress = False
        if result.get("ok"):
            self.apply_screen_bundle(result.get("bundle") or {})
        if self.refresh_queued:
            self.refresh_queued = False
            QTimer.singleShot(0, self.refresh_all)

    def apply_screen_bundle(self, bundle):
        today = bundle.get("today", {"title": "Today", "summary": {}, "out_rows": [], "in_rows": []})
        tomorrow = bundle.get("tomorrow", {"title": "Tomorrow", "summary": {}, "out_rows": [], "in_rows": []})
        prep = bundle.get("prep", {"title": "Prep", "summary": {}, "rows": []})
        outstanding = bundle.get("outstanding", {"title": "Outstanding", "summary": {}, "rows": []})
        notifications = bundle.get("notifications", {"title": "Notifications", "summary": {}, "rows": []})

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
            ["Job Name", "Job Number", "Delivery Date", "Prep Status", "Owner", "Action"],
            prep.get("rows", []),
        )
        self.add_prep_action_buttons()
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

    def add_prep_action_buttons(self):
        try:
            action_col = self.prep_table.headers_for_data.index("Action")
        except ValueError:
            return

        self.prep_table.set_touch_row_height(74)
        self.prep_table.horizontalHeader().setSectionResizeMode(action_col, QHeaderView.Fixed)
        self.prep_table.setColumnWidth(action_col, 310)

        for row in range(self.prep_table.rowCount()):
            data = self.prep_table.row_data(row)
            items = data.get("__unprepped_items", [])
            unprepped_qty = sum(int(item.get("Unprepped", 0) or 0) for item in items)
            button = QPushButton(f"VIEW UNPREPPED ({unprepped_qty})" if items else "ALL PREPPED")
            button.setObjectName("prepActionButton")
            button.setMinimumHeight(56)
            button.setEnabled(bool(items))
            button.clicked.connect(lambda _checked=False, row_index=row: self.open_unprepped_items_dialog(row_index, 0))
            self.prep_table.setCellWidget(row, action_col, button)

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
    if not acquire_viewer_lock():
        sys.exit(0)
    app = QApplication(sys.argv)
    win = ViewerWindow()
    win.show()
    sys.exit(app.exec())

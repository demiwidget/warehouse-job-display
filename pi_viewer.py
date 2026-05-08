import json
import os
import shutil
import subprocess
import sys
from tempfile import NamedTemporaryFile
import time
from pathlib import Path
from threading import Thread
from urllib.parse import quote

os.environ.setdefault("QT_IM_MODULE", "none")
os.environ.setdefault("QT_VIRTUALKEYBOARD_DESKTOP_DISABLE", "1")

import requests
from PySide6.QtCore import QObject, QEvent, QPoint, QTimer, Qt, QUrl, Signal
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
    QGridLayout,
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
from pi_identity import normalize_display_scale, registration_id, registration_payload
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
    "display_scale": 100,
    "audio_output": "hdmi",
    "audio_volume": 100,
}

RANK_COLORS = (
    "#c6ead0",
    "#d7e8b3",
    "#ece6a9",
    "#f0d19d",
    "#edba9d",
    "#eaa4a0",
    "#df8f98",
    "#c97886",
)


def scaled(value, scale=1.0, minimum=1):
    return max(minimum, int(round(float(value) * float(scale))))


def rank_color(index, total):
    if total <= 1:
        return RANK_COLORS[0]
    palette_index = round(index * (len(RANK_COLORS) - 1) / max(total - 1, 1))
    return RANK_COLORS[max(0, min(len(RANK_COLORS) - 1, palette_index))]


def readable_text_color(background):
    color = QColor(background)
    brightness = ((color.red() * 299) + (color.green() * 587) + (color.blue() * 114)) / 1000
    return "#071012" if brightness > 150 else "#ffffff"


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


def _event_position(event):
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
            self.start_pos = _event_position(event)
            self.last_pos = self.start_pos
            return False

        if event_type == QEvent.MouseMove and self.pressed and event.buttons() & Qt.LeftButton:
            pos = _event_position(event)
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
            self.scroll_widget.horizontalScrollBar().setValue(
                self.scroll_widget.horizontalScrollBar().value() - delta.x()
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


def enable_click_drag_scroll(widget):
    """Allow touch and mouse-drag scrolling on scrollable Qt widgets."""
    viewport = widget.viewport() if hasattr(widget, "viewport") else widget
    viewport.setAttribute(Qt.WA_AcceptTouchEvents, True)
    QScroller.grabGesture(viewport, QScroller.TouchGesture)
    QScroller.grabGesture(viewport, QScroller.LeftMouseButtonGesture)
    drag_filter = DragScrollFilter(widget)
    viewport.installEventFilter(drag_filter)
    widget._warehouse_drag_scroll_filter = drag_filter


class DashboardTable(QTableWidget):
    def __init__(self, parent=None, scale=1.0):
        super().__init__(parent)
        self.ui_scale = float(scale or 1.0)
        self.row_payloads = []
        self.headers_for_data = []
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(scaled(42, self.ui_scale))
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.horizontalHeader().setStretchLastSection(False)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.horizontalHeader().setMinimumSectionSize(scaled(90, self.ui_scale))
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
    def __init__(self, title_out, title_in, scale=1.0):
        super().__init__()
        self.ui_scale = float(scale or 1.0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(scaled(14, self.ui_scale))

        self.out_label = QLabel(title_out)
        self.out_label.setObjectName("sectionHeading")
        self.out_table = DashboardTable(scale=self.ui_scale)
        self.in_label = QLabel(title_in)
        self.in_label.setObjectName("sectionHeading")
        self.in_table = DashboardTable(scale=self.ui_scale)

        layout.addWidget(self.out_label)
        layout.addWidget(self.out_table, 1)
        layout.addWidget(self.in_label)
        layout.addWidget(self.in_table, 1)


class UnpreppedItemsDialog(QDialog):
    def __init__(self, job_name, job_number, items, parent=None):
        super().__init__(parent)
        self.ui_scale = float(getattr(parent, "ui_scale", 1.0) or 1.0)
        self.setWindowTitle(f"Unprepped Items - {job_name}")
        self.resize(scaled(1000, self.ui_scale), scaled(650, self.ui_scale))

        layout = QVBoxLayout(self)
        heading = QLabel(f"<h2>{job_name} <span style='font-weight:400'>(#{job_number})</span></h2>")
        sub = QLabel("Items below are not yet fully prepared.")
        table = DashboardTable(scale=self.ui_scale)
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
        self.ui_scale = float(getattr(parent, "ui_scale", 1.0) or 1.0)
        self.acknowledged = False
        self.setWindowTitle(title or "Notification")
        self.resize(scaled(1200, self.ui_scale), scaled(760, self.ui_scale))
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
        self.accent = accent
        layout = QVBoxLayout(self)

        self.title = QLabel(title)
        self.value = QLabel("0")
        self.value.setAlignment(Qt.AlignCenter)
        self.caption = QLabel("")
        self.caption.setAlignment(Qt.AlignCenter)
        self.caption.setWordWrap(True)

        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.caption)
        self.apply_scale(1.0)

    def apply_scale(self, scale=1.0):
        scale = float(scale or 1.0)
        self.title.setStyleSheet(f"font-size:{scaled(16, scale)}px; font-weight:700; color:{self.accent};")
        self.value.setStyleSheet(
            f"font-size:{scaled(34, scale)}px; font-weight:700; padding:{scaled(8, scale)}px;"
        )
        self.caption.setStyleSheet(f"font-size:{scaled(13, scale)}px; color:#bbb;")
        self.setMinimumHeight(scaled(118, scale))
        self.setStyleSheet(
            f"background:#15181b; border:1px solid #22282e; "
            f"border-radius:{scaled(12, scale)}px; padding:{scaled(8, scale)}px;"
        )

    def set_data(self, value, caption=""):
        self.value.setText(str(value))
        self.caption.setText(caption)


class LeaderboardCard(QWidget):
    def __init__(self, title, accent="#ffb000"):
        super().__init__()
        self.accent = accent
        self.ui_scale = 1.0
        self.rank_labels = []
        layout = QHBoxLayout(self)
        layout.setSpacing(scaled(10, self.ui_scale))

        left = QVBoxLayout()
        left.setSpacing(scaled(2, self.ui_scale))
        self.title = QLabel(title)
        self.title.setAlignment(Qt.AlignCenter)
        self.value = QLabel("0")
        self.value.setAlignment(Qt.AlignCenter)
        self.caption = QLabel("total quarantines")
        self.caption.setAlignment(Qt.AlignCenter)
        self.caption.setWordWrap(True)
        left.addWidget(self.title)
        left.addWidget(self.value)
        left.addWidget(self.caption)

        self.rows_widget = QWidget()
        self.rows_grid = QGridLayout(self.rows_widget)
        self.rows_grid.setContentsMargins(0, 0, 0, 0)
        self.rows_grid.setSpacing(scaled(6, self.ui_scale))

        layout.addLayout(left, 1)
        layout.addWidget(self.rows_widget, 5)
        self.apply_scale(1.0)

    def apply_scale(self, scale=1.0):
        scale = float(scale or 1.0)
        self.ui_scale = scale
        self.title.setStyleSheet(f"font-size:{scaled(14, scale)}px; font-weight:800; color:{self.accent};")
        self.value.setStyleSheet(f"font-size:{scaled(30, scale)}px; font-weight:850; padding:{scaled(2, scale)}px;")
        self.caption.setStyleSheet(f"font-size:{scaled(11, scale)}px; color:#9fa8ad;")
        self.layout().setSpacing(scaled(10, scale))
        self.rows_grid.setSpacing(scaled(6, scale))
        for index, label in enumerate(self.rank_labels):
            self._style_rank_label(label, rank_color(index, max(1, len(self.rank_labels))))
        self.setMinimumHeight(scaled(88, scale))
        self.setStyleSheet(
            f"background:#15181b; border:1px solid #2b2f23; "
            f"border-left:{scaled(4, scale)}px solid {self.accent}; "
            f"border-radius:{scaled(11, scale)}px; padding:{scaled(6, scale)}px;"
        )

    def _clear_rank_labels(self):
        self.rank_labels = []
        while self.rows_grid.count():
            item = self.rows_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _style_rank_label(self, label, background):
        label.setMinimumHeight(scaled(34, self.ui_scale))
        label.setStyleSheet(
            f"background:{background}; color:#000000; "
            f"border:0; border-radius:{scaled(7, self.ui_scale)}px; "
            f"padding:{scaled(3, self.ui_scale)}px {scaled(6, self.ui_scale)}px; "
            f"font-size:{scaled(16, self.ui_scale)}px; font-weight:850;"
        )

    def set_data(self, total, rows, status=""):
        self.value.setText(str(total))
        self.caption.setText(str(status or "total quarantines"))
        self._clear_rank_labels()

        display_rows = list(rows or [])[:8]
        if not display_rows:
            placeholder = QLabel("No department data yet")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setWordWrap(True)
            placeholder.setStyleSheet(
                f"font-size:{scaled(18, self.ui_scale)}px; font-weight:800; color:#f3f3f3;"
            )
            self.rank_labels.append(placeholder)
            self.rows_grid.addWidget(placeholder, 0, 0)
            return

        column_count = max(1, len(display_rows))
        total_rows = len(display_rows)
        for index, row in enumerate(display_rows):
            rank = row.get("Rank", "")
            department = row.get("Department", "Unknown")
            count = row.get("Quarantines", 0)
            label = QLabel(f"#{rank} {department}: {count}")
            label.setAlignment(Qt.AlignCenter)
            label.setWordWrap(False)
            self._style_rank_label(label, rank_color(index, total_rows))
            self.rank_labels.append(label)
            self.rows_grid.addWidget(label, index // column_count, index % column_count)


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
        self.display_scale = normalize_display_scale(self.config.get("display_scale", 100))
        self.ui_scale = self.display_scale / 100.0
        self.pending_alerts = []
        self.remote_alert_queue_remaining = 0
        self.active_alert_dialog = None
        self.sound_effect = QSoundEffect(self) if QSoundEffect else None
        self.sound_process = None
        self.last_audio_apply_at = 0.0
        self.last_audio_message = ""
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
        root.setContentsMargins(
            scaled(10, self.ui_scale),
            scaled(10, self.ui_scale),
            scaled(10, self.ui_scale),
            scaled(10, self.ui_scale),
        )
        root.setSpacing(scaled(10, self.ui_scale))

        cards = QGridLayout()
        cards.setSpacing(scaled(10, self.ui_scale))
        self.card_quarantines = LeaderboardCard("Quarantines")
        self.card_today_out = SummaryCard("Today Out")
        self.card_today_in = SummaryCard("Today In", "#9bc53d")
        self.card_tomorrow_out = SummaryCard("Tomorrow Out", "#fde74c")
        self.card_tomorrow_in = SummaryCard("Tomorrow In", "#e55934")
        self.card_prep = SummaryCard("Prep", "#5bc0eb")
        self.card_outstanding = SummaryCard("Outstanding", "#c3423f")
        self.summary_cards = [
            self.card_quarantines,
            self.card_today_out,
            self.card_today_in,
            self.card_tomorrow_out,
            self.card_tomorrow_in,
            self.card_prep,
            self.card_outstanding,
        ]
        for card in self.summary_cards:
            card.apply_scale(self.ui_scale)
        cards.addWidget(self.card_quarantines, 0, 0, 1, 4)
        cards.addWidget(self.card_today_out, 1, 0)
        cards.addWidget(self.card_today_in, 1, 1)
        cards.addWidget(self.card_tomorrow_out, 1, 2)
        cards.addWidget(self.card_tomorrow_in, 1, 3)
        cards.addWidget(self.card_prep, 2, 0, 1, 2)
        cards.addWidget(self.card_outstanding, 2, 2, 1, 2)
        root.addLayout(cards)

        alert_bar = QHBoxLayout()
        alert_bar.addStretch(1)
        self.alert_queue_badge = QLabel("")
        self.alert_queue_badge.setObjectName("alertQueueBadge")
        self.alert_queue_badge.hide()
        alert_bar.addWidget(self.alert_queue_badge)
        root.addLayout(alert_bar)

        self.tabs = QTabWidget()
        self.today_page = CombinedJobsPage(
            "Jobs Collecting / Delivering Today",
            "Jobs Returning Today",
            scale=self.ui_scale,
        )
        self.tomorrow_page = CombinedJobsPage(
            "Jobs Collecting / Delivering Tomorrow",
            "Jobs Returning Tomorrow",
            scale=self.ui_scale,
        )
        self.prep_table = DashboardTable(scale=self.ui_scale)
        self.outstanding_table = DashboardTable(scale=self.ui_scale)
        self.notifications_table = DashboardTable(scale=self.ui_scale)

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
        scale = self.ui_scale
        self.setStyleSheet(
            f"""
            QMainWindow, QWidget {{ background-color: #111315; color: #f3f3f3; font-size: {scaled(14, scale)}px; }}
            QTableWidget {{ background-color: #171a1d; gridline-color: #2a2f35; alternate-background-color: #1d2126; border: 1px solid #2a2f35; border-radius: {scaled(12, scale)}px; font-size: {scaled(16, scale)}px; selection-background-color: #27445d; }}
            QTableWidget::item {{ padding: {scaled(10, scale)}px; height: {scaled(34, scale)}px; }}
            QHeaderView::section {{ background-color: #1f252b; color: #f3f3f3; padding: {scaled(10, scale)}px; border: none; border-bottom: 1px solid #2a2f35; font-size: {scaled(15, scale)}px; font-weight: 600; }}
            QTabWidget::pane {{ border: 1px solid #2a2f35; border-radius: {scaled(14, scale)}px; }}
            QTabBar::tab {{ background: #1a1f24; color: #dcdcdc; padding: {scaled(12, scale)}px {scaled(20, scale)}px; border-top-left-radius: {scaled(10, scale)}px; border-top-right-radius: {scaled(10, scale)}px; font-size: {scaled(14, scale)}px; }}
            QTabBar::tab:selected {{ background: #2b343d; }}
            QPushButton {{ background-color: #2b343d; color: white; padding: {scaled(10, scale)}px {scaled(14, scale)}px; border-radius: {scaled(10, scale)}px; font-size: {scaled(14, scale)}px; }}
            QPushButton:hover {{ background-color: #36424d; }}
            QPushButton#prepActionButton {{
                background-color: #f4c542;
                color: #111315;
                font-size: {scaled(18, scale)}px;
                font-weight: 800;
                padding: {scaled(14, scale)}px {scaled(18, scale)}px;
                border: 2px solid #fff0a6;
                border-radius: {scaled(8, scale)}px;
            }}
            QPushButton#prepActionButton:disabled {{
                background-color: #343a40;
                color: #8e979f;
                border: 1px solid #4a525a;
            }}
            QLabel {{ color: #f3f3f3; }}
            QLabel#sectionHeading {{ font-size: {scaled(22, scale)}px; font-weight: 700; padding: {scaled(8, scale)}px {scaled(4, scale)}px; }}
            QLabel#alertQueueBadge {{
                background-color: #c3423f;
                color: white;
                font-size: {scaled(15, scale)}px;
                font-weight: 700;
                padding: {scaled(8, scale)}px {scaled(14, scale)}px;
                border-radius: {scaled(14, scale)}px;
            }}
            QStatusBar {{ background-color: #15181b; font-size: {scaled(13, scale)}px; }}
            QTextBrowser {{ background-color: #171a1d; border: 1px solid #2a2f35; border-radius: {scaled(12, scale)}px; padding: {scaled(16, scale)}px; font-size: {scaled(18, scale)}px; }}
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
            alert = response.json()
            if alert and alert.get("play_sound"):
                sound_path = self.prepare_alert_sound(alert.get("sound", ""))
                if sound_path:
                    alert["_sound_path"] = str(sound_path)
            result = {"ok": True, "alert": alert}
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
            self.play_alert_sound(alert.get("sound", ""), alert.get("_sound_path"))
            alert["_sound_played"] = True
        self.pending_alerts.insert(0, alert)
        self.update_notification_queue_badge()
        self.show_next_alert()

    def show_next_alert(self):
        if self.active_alert_dialog or not self.pending_alerts:
            return

        alert = self.pending_alerts.pop(0)
        self.update_notification_queue_badge()
        if alert.get("play_sound") and not alert.get("_sound_played"):
            self.play_alert_sound(alert.get("sound", ""), alert.get("_sound_path"))

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

    def report_audio_event(self, message, level="info"):
        Thread(
            target=lambda: post_status(
                self.config,
                "online",
                message,
                source="audio",
                timeout=2,
                event_only=True,
                level=level,
            ),
            daemon=True,
        ).start()

    def safe_sound_name(self, sound_name):
        raw_name = str(sound_name or "").strip()
        if not raw_name or "/" in raw_name or "\\" in raw_name:
            return ""
        safe_name = Path(raw_name).name
        if safe_name != raw_name or Path(safe_name).suffix.lower() != ".wav":
            return ""
        return safe_name

    def local_sound_path(self, sound_name):
        safe_name = self.safe_sound_name(sound_name)
        if not safe_name:
            return None
        return BASE_DIR / "sounds" / safe_name

    def prepare_alert_sound(self, sound_name):
        sound_path = self.local_sound_path(sound_name)
        if sound_path is None:
            self.report_audio_event(f"Invalid alert sound name: {sound_name}", level="warning")
            return None

        if self.download_sound_file(sound_path.name, sound_path):
            self.report_audio_event(f"Downloaded alert sound {sound_path.name}.")
            return sound_path
        if sound_path.exists():
            self.report_audio_event(f"Using cached alert sound {sound_path.name}.", level="warning")
            return sound_path
        self.report_audio_event(f"Alert sound {sound_path.name} is missing on this Pi.", level="warning")
        return None

    def download_sound_file(self, sound_name, target_path):
        temp_path = target_path.with_name(f".{target_path.name}.download.tmp")
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            response = requests.get(self.server_url(f"/sounds/{quote(sound_name, safe='')}"), timeout=5)
            response.raise_for_status()
            data = response.content
            if not data or len(data) > 10 * 1024 * 1024:
                self.report_audio_event(f"Rejected alert sound {sound_name}: invalid download size.", level="warning")
                return False
            temp_path.write_bytes(data)
            temp_path.replace(target_path)
            return True
        except Exception as error:
            self.report_audio_event(f"Could not download alert sound {sound_name}: {error}", level="warning")
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
            return False

    def play_alert_sound(self, sound_name, prepared_path=None):
        self.ensure_audio_preferences()
        sound_path = Path(prepared_path) if prepared_path else self.local_sound_path(sound_name)
        if sound_path is None or not sound_path.exists():
            self.report_audio_event(f"Could not play alert sound {sound_name}: file is missing.", level="warning")
            QApplication.beep()
            return

        player = self.play_alert_sound_with_system_player(sound_path)
        if player:
            self.report_audio_event(f"Started alert sound {sound_path.name} using {player}.")
            return

        if self.sound_effect:
            self.sound_effect.stop()
            self.sound_effect.setSource(QUrl.fromLocalFile(str(sound_path)))
            self.sound_effect.setLoopCount(1)
            self.sound_effect.setVolume(0.9)
            self.sound_effect.play()
            self.report_audio_event(f"Started alert sound {sound_path.name} using Qt audio.")
            return
        self.report_audio_event(f"Could not start alert sound {sound_path.name}; used system beep.", level="warning")
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
                    return binary
                if return_code == 0:
                    return binary
            except Exception:
                continue
        return None

    def ensure_audio_preferences(self, force=False):
        now = time.monotonic()
        if not force and (now - self.last_audio_apply_at) < 20:
            return
        ok, message = apply_audio_preferences(self.config)
        if message and (force or message != self.last_audio_message):
            level = "info" if ok else "warning"
            prefix = "Audio output set to" if ok else "Audio output not ready:"
            self.report_audio_event(f"{prefix} {message}", level=level)
            self.last_audio_message = message
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
        quarantines = bundle.get("quarantines", {"title": "Quarantines", "summary": {}, "rows": []})

        quarantine_summary = quarantines.get("summary", {}) or {}
        self.card_quarantines.set_data(
            quarantine_summary.get("Total", 0),
            quarantines.get("rows", []),
            quarantine_summary.get("Status", "total quarantines"),
        )
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

        self.prep_table.set_touch_row_height(scaled(74, self.ui_scale))
        self.prep_table.horizontalHeader().setSectionResizeMode(action_col, QHeaderView.Fixed)
        self.prep_table.setColumnWidth(action_col, scaled(310, self.ui_scale))

        for row in range(self.prep_table.rowCount()):
            data = self.prep_table.row_data(row)
            items = data.get("__unprepped_items", [])
            unprepped_qty = sum(int(item.get("Unprepped", 0) or 0) for item in items)
            button = QPushButton(f"VIEW UNPREPPED ({unprepped_qty})" if items else "ALL PREPPED")
            button.setObjectName("prepActionButton")
            button.setMinimumHeight(scaled(56, self.ui_scale))
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

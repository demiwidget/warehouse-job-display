import json
import os
import shutil
import subprocess
import sys
from html import escape
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
    QScrollArea,
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
from pi_audio import apply_audio_preferences, audio_health_report, sync_audio_config
from pi_identity import normalize_compact_layout, normalize_display_scale, registration_id, registration_payload
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
    "compact_layout": "auto",
    "audio_output": "hdmi",
    "audio_volume": 100,
    "maintenance": {
        "enabled": False,
        "text": "Maintenance in progress\nPlease wait",
        "background": "#050505",
        "foreground": "#ffffff",
    },
}

RANK_COLORS = (
    "#58b96f",
    "#7fbd5a",
    "#b6bd52",
    "#d7ad48",
    "#dc8f3f",
    "#d66e42",
    "#c84f49",
    "#ad3444",
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


def safe_int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except Exception:
        return default


def as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def valid_color(value, default):
    color = QColor(str(value or "").strip())
    return color.name() if color.isValid() else default


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


class OutstandingItemsDialog(QDialog):
    def __init__(self, job_name, job_number, items, booked_out_qty=0, parent=None):
        super().__init__(parent)
        self.ui_scale = float(getattr(parent, "ui_scale", 1.0) or 1.0)
        self.setWindowTitle(f"Outstanding Items - {job_name}")
        self.resize(scaled(900, self.ui_scale), scaled(600, self.ui_scale))

        layout = QVBoxLayout(self)
        heading = QLabel(f"<h2>{job_name} <span style='font-weight:400'>(#{job_number})</span></h2>")
        sub = QLabel("Items below are still booked out and awaiting check-in.")
        table = DashboardTable(scale=self.ui_scale)
        rows = list(items or [])
        if not rows and booked_out_qty > 0:
            rows = [
                {
                    "Item": "Outstanding item detail not available yet",
                    "Code": "",
                    "Outstanding": booked_out_qty,
                    "Checked In": "",
                    "Status": "Update or refresh the Manager Pi to load the item list.",
                    "Booked Out Detail": "",
                }
            ]
        table.set_rows(["Item", "Code", "Outstanding", "Checked In", "Status", "Booked Out Detail"], rows)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)

        layout.addWidget(heading)
        layout.addWidget(sub)
        layout.addWidget(table, 1)
        layout.addWidget(close_btn)


class AlertDialog(QDialog):
    def __init__(self, title, html, parent=None, show_clear_all=False, clear_all_callback=None):
        super().__init__(parent)
        self.ui_scale = float(getattr(parent, "ui_scale", 1.0) or 1.0)
        self.acknowledged = False
        self.clear_all_callback = clear_all_callback
        self.setWindowTitle(title or "Notification")
        self.resize_to_screen()
        self.setModal(True)
        flags = self.windowFlags()
        flags |= Qt.WindowStaysOnTopHint
        flags &= ~Qt.WindowCloseButtonHint
        self.setWindowFlags(flags)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            scaled(24, self.ui_scale),
            scaled(20, self.ui_scale),
            scaled(24, self.ui_scale),
            scaled(20, self.ui_scale),
        )
        layout.setSpacing(scaled(14, self.ui_scale))

        header_row = QHBoxLayout()
        heading = QLabel(f"<h1>{title or 'Notification'}</h1>")
        heading.setWordWrap(True)
        header_row.addWidget(heading, 1)
        if show_clear_all:
            header_row.addWidget(
                self.make_action_button("Clear All", self.clear_all_notifications, primary=False)
            )
        top_confirm_btn = self.make_action_button("Confirm", self.confirm_notification, primary=True)
        top_confirm_btn.setDefault(True)
        header_row.addWidget(top_confirm_btn)

        body = QTextBrowser()
        body.setHtml(html or "")
        body.setOpenExternalLinks(True)
        enable_click_drag_scroll(body)

        close_btn = self.make_action_button("Confirm Notification", self.confirm_notification, primary=True)
        button_row = QHBoxLayout()
        if show_clear_all:
            clear_all_btn = self.make_action_button(
                "Clear All Notifications", self.clear_all_notifications, primary=False
            )
            button_row.addWidget(clear_all_btn)
        button_row.addStretch(1)
        button_row.addWidget(close_btn)

        layout.addLayout(header_row)
        layout.addWidget(body, 1)
        layout.addLayout(button_row)

    def resize_to_screen(self):
        width = scaled(1200, self.ui_scale)
        height = scaled(760, self.ui_scale)
        screen = QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            width = min(width, int(available.width() * 0.94))
            height = min(height, int(available.height() * 0.88))
        self.resize(width, height)

    def make_action_button(self, text, slot, primary=False):
        button = QPushButton(text)
        button.clicked.connect(slot)
        button.setMinimumHeight(scaled(56, self.ui_scale))
        button.setMinimumWidth(scaled(150 if primary else 140, self.ui_scale))
        if primary:
            button.setStyleSheet(
                "QPushButton { background:#57d68d; color:#06100b; border:0; "
                "border-radius:12px; padding:12px 18px; font-weight:900; font-size:18px; }"
                "QPushButton:pressed { background:#35b76d; }"
            )
        else:
            button.setStyleSheet(
                "QPushButton { background:#ffd166; color:#150f00; border:0; "
                "border-radius:12px; padding:12px 18px; font-weight:900; font-size:18px; }"
                "QPushButton:pressed { background:#f2b94d; }"
            )
        return button

    def confirm_notification(self):
        self.acknowledged = True
        self.accept()

    def clear_all_notifications(self):
        self.acknowledged = True
        if callable(self.clear_all_callback):
            self.clear_all_callback()
            return
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
            count_style = f"font-size:{scaled(21, self.ui_scale)}px; font-weight:1000;"
            label = QLabel(
                f"#{escape(str(rank))} {escape(str(department))}: "
                f"<span style='{count_style}'>{escape(str(count))}</span>"
            )
            label.setTextFormat(Qt.RichText)
            label.setAlignment(Qt.AlignCenter)
            label.setWordWrap(False)
            self._style_rank_label(label, rank_color(index, total_rows))
            self.rank_labels.append(label)
            self.rows_grid.addWidget(label, index // column_count, index % column_count)


class CompactMetricCard(QWidget):
    def __init__(self, title, accent="#5bc0eb", scale=1.0):
        super().__init__()
        self.title_text = title
        self.accent = accent
        self.ui_scale = float(scale or 1.0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            scaled(10, self.ui_scale),
            scaled(8, self.ui_scale),
            scaled(10, self.ui_scale),
            scaled(8, self.ui_scale),
        )
        layout.setSpacing(scaled(3, self.ui_scale))
        self.title = QLabel(title)
        self.value = QLabel("0")
        self.caption = QLabel("")
        self.caption.setWordWrap(True)
        self.value.setAlignment(Qt.AlignLeft)
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.caption)
        self.apply_style()

    def apply_style(self):
        self.title.setStyleSheet(
            f"color:{self.accent}; font-size:{scaled(12, self.ui_scale)}px; font-weight:900; "
            "letter-spacing:0.5px;"
        )
        self.value.setStyleSheet(
            f"color:#ffffff; font-size:{scaled(25, self.ui_scale)}px; font-weight:1000;"
        )
        self.caption.setStyleSheet(
            f"color:#b7c0c8; font-size:{scaled(10, self.ui_scale)}px; font-weight:700;"
        )
        self.setMinimumHeight(scaled(82, self.ui_scale))
        self.setStyleSheet(
            f"background:#161b20; border:1px solid #26323a; "
            f"border-left:{scaled(5, self.ui_scale)}px solid {self.accent}; "
            f"border-radius:{scaled(12, self.ui_scale)}px;"
        )

    def set_data(self, value, caption=""):
        self.value.setText(str(value))
        self.caption.setText(str(caption or ""))


class CompactOverviewPage(QScrollArea):
    def __init__(self, scale=1.0):
        super().__init__()
        self.ui_scale = float(scale or 1.0)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(
            scaled(6, self.ui_scale),
            scaled(6, self.ui_scale),
            scaled(6, self.ui_scale),
            scaled(6, self.ui_scale),
        )
        layout.setSpacing(scaled(8, self.ui_scale))

        heading = QLabel("Warehouse Overview")
        heading.setObjectName("compactOverviewHeading")
        subtitle = QLabel("Tap a tab below for the full list.")
        subtitle.setObjectName("compactOverviewSubtitle")
        layout.addWidget(heading)
        layout.addWidget(subtitle)

        grid_widget = QWidget()
        self.grid = QGridLayout(grid_widget)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(scaled(8, self.ui_scale))

        self.cards = {
            "today_out": CompactMetricCard("Today Out", "#4cc9f0", self.ui_scale),
            "today_in": CompactMetricCard("Today In", "#9bc53d", self.ui_scale),
            "tomorrow_out": CompactMetricCard("Tomorrow Out", "#f4d35e", self.ui_scale),
            "tomorrow_in": CompactMetricCard("Tomorrow In", "#ee6c4d", self.ui_scale),
            "prep": CompactMetricCard("Prep", "#5bc0eb", self.ui_scale),
            "outstanding": CompactMetricCard("Outstanding", "#ff5a5f", self.ui_scale),
            "unreturned": CompactMetricCard("Unreturned", "#ffb000", self.ui_scale),
            "quarantines": CompactMetricCard("Quarantines", "#80ed99", self.ui_scale),
        }
        for index, card in enumerate(self.cards.values()):
            self.grid.addWidget(card, index // 2, index % 2)
        layout.addWidget(grid_widget)
        layout.addStretch(1)
        self.setWidget(content)
        enable_click_drag_scroll(self)

    def set_data(self, metrics):
        for key, card in self.cards.items():
            value, caption = metrics.get(key, ("0", ""))
            card.set_data(value, caption)


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
    compact_layout = normalize_compact_layout(cfg.get("compact_layout", "auto"))
    if cfg.get("compact_layout") != compact_layout:
        cfg["compact_layout"] = compact_layout
        changed = True
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
    clear_alerts_result_ready = Signal(object)

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.config_mtime = self.config_file_mtime()
        self.current_screen = self.config.get("screen", "today")
        self.display_scale = normalize_display_scale(self.config.get("display_scale", 100))
        self.ui_scale = self.display_scale / 100.0
        self.compact_layout_mode = normalize_compact_layout(self.config.get("compact_layout", "auto"))
        self.compact_display = self.should_use_compact_display()
        self.maintenance_enabled = False
        self.pending_alerts = []
        self.remote_alert_queue_remaining = 0
        self.active_alert_dialog = None
        self.clearing_alerts = False
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
        self.build_maintenance_overlay()
        self.apply_theme()
        self.apply_maintenance_config(self.config.get("maintenance", {}))
        self.showFullScreen()
        self.refresh_result_ready.connect(self.handle_refresh_result)
        self.alert_result_ready.connect(self.handle_alert_result)
        self.clear_alerts_result_ready.connect(self.handle_clear_alerts_result)

        self.register_timer = QTimer(self)
        self.register_timer.timeout.connect(self.register)
        self.register_timer.start(10000)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_all)
        self.refresh_timer.start(3000)

        self.alert_timer = QTimer(self)
        self.alert_timer.timeout.connect(self.poll_alerts)
        self.alert_timer.start(2500)

        self.config_timer = QTimer(self)
        self.config_timer.timeout.connect(self.refresh_runtime_config)
        self.config_timer.start(1500)

        self.set_current_tab()
        self.register()
        self.refresh_all()
        QTimer.singleShot(800, self.ensure_audio_preferences)
        QTimer.singleShot(5000, self.ensure_audio_preferences)
        QTimer.singleShot(7000, self.report_audio_health)
        QTimer.singleShot(1200, self.report_online_status)

    def build_ui(self):
        from PySide6.QtWidgets import QGridLayout

        central = QWidget()
        root = QVBoxLayout(central)
        margin = 4 if self.compact_display else 10
        spacing = 4 if self.compact_display else 10
        root.setContentsMargins(
            scaled(margin, self.ui_scale),
            scaled(margin, self.ui_scale),
            scaled(margin, self.ui_scale),
            scaled(margin, self.ui_scale),
        )
        root.setSpacing(scaled(spacing, self.ui_scale))

        self.cards_widget = QWidget()
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
        self.cards_widget.setLayout(cards)
        root.addWidget(self.cards_widget)
        if self.compact_display:
            self.cards_widget.hide()

        self.compact_header = QWidget()
        compact_header_layout = QHBoxLayout(self.compact_header)
        compact_header_layout.setContentsMargins(
            scaled(6, self.ui_scale),
            scaled(4, self.ui_scale),
            scaled(6, self.ui_scale),
            scaled(4, self.ui_scale),
        )
        compact_header_layout.setSpacing(scaled(8, self.ui_scale))
        self.compact_screen_label = QLabel("")
        self.compact_screen_label.setObjectName("compactScreenLabel")
        self.compact_meta_label = QLabel("")
        self.compact_meta_label.setObjectName("compactMetaLabel")
        compact_header_layout.addWidget(self.compact_screen_label, 1)
        compact_header_layout.addWidget(self.compact_meta_label)
        root.addWidget(self.compact_header)
        if not self.compact_display:
            self.compact_header.hide()

        alert_bar = QHBoxLayout()
        alert_bar.addStretch(1)
        self.alert_queue_badge = QLabel("")
        self.alert_queue_badge.setObjectName("alertQueueBadge")
        self.alert_queue_badge.hide()
        alert_bar.addWidget(self.alert_queue_badge)
        self.clear_alerts_button = QPushButton("Clear All Notifications")
        self.clear_alerts_button.setObjectName("clearAlertsButton")
        self.clear_alerts_button.clicked.connect(self.clear_all_notifications)
        self.clear_alerts_button.hide()
        alert_bar.addWidget(self.clear_alerts_button)
        root.addLayout(alert_bar)

        self.tabs = QTabWidget()
        self.screen_tab_indexes = {}
        if self.compact_display:
            self.compact_overview_page = CompactOverviewPage(scale=self.ui_scale)
            self.screen_tab_indexes["overview"] = self.tabs.addTab(self.compact_overview_page, "Home")
        else:
            self.compact_overview_page = None

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
        self.unreturned_table = DashboardTable(scale=self.ui_scale)
        self.notifications_table = DashboardTable(scale=self.ui_scale)
        self.quarantines_table = DashboardTable(scale=self.ui_scale) if self.compact_display else None

        self.screen_tab_indexes["today"] = self.tabs.addTab(self.today_page, "Today")
        self.screen_tab_indexes["tomorrow"] = self.tabs.addTab(self.tomorrow_page, "Tomorrow")
        self.screen_tab_indexes["prep"] = self.tabs.addTab(
            self.prep_table,
            "Prep" if self.compact_display else "Prep Status",
        )
        self.screen_tab_indexes["outstanding"] = self.tabs.addTab(
            self.outstanding_table,
            "Outstanding" if self.compact_display else "Outstanding Items",
        )
        self.screen_tab_indexes["unreturned"] = self.tabs.addTab(
            self.unreturned_table,
            "Unreturned" if self.compact_display else "Unreturned Jobs",
        )
        if self.compact_display and self.quarantines_table is not None:
            self.screen_tab_indexes["quarantines"] = self.tabs.addTab(self.quarantines_table, "Quarantines")
        self.screen_tab_indexes["notifications"] = self.tabs.addTab(
            self.notifications_table,
            "Alerts" if self.compact_display else "Notification History",
        )
        self.prep_table.cellDoubleClicked.connect(self.open_unprepped_items_dialog)
        self.outstanding_table.cellDoubleClicked.connect(self.open_outstanding_items_dialog)
        self.tabs.currentChanged.connect(lambda _index: self.update_compact_header())

        root.addWidget(self.tabs)
        self.setCentralWidget(central)

        status = QStatusBar()
        self.setStatusBar(status)
        self.version_label = QLabel(f"v{self.config.get('version', 'unknown')}")
        self.last_refresh = QLabel("Last refresh: never")
        status.addPermanentWidget(self.version_label)
        status.addPermanentWidget(self.last_refresh)
        if self.compact_display:
            status.hide()

        menubar = self.menuBar()
        view_menu = menubar.addMenu("View")
        refresh_action = QAction("Refresh now", self)
        refresh_action.triggered.connect(self.refresh_all)
        fullscreen_action = QAction("Toggle fullscreen", self)
        fullscreen_action.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(refresh_action)
        view_menu.addAction(fullscreen_action)
        if self.compact_display:
            menubar.hide()
            self.tabs.tabBar().setUsesScrollButtons(True)
            self.tabs.setElideMode(Qt.ElideRight)
            self.tabs.setDocumentMode(True)
        self.update_compact_header()

    def should_use_compact_display(self):
        if self.compact_layout_mode == "compact":
            return True
        if self.compact_layout_mode == "standard":
            return False
        screen = QApplication.primaryScreen()
        if not screen:
            return False
        geometry = screen.availableGeometry()
        return geometry.height() <= 650 or geometry.width() <= 900

    def build_maintenance_overlay(self):
        self.maintenance_overlay = QWidget(self)
        self.maintenance_overlay.setAttribute(Qt.WA_StyledBackground, True)
        self.maintenance_overlay.hide()
        overlay_layout = QVBoxLayout(self.maintenance_overlay)
        overlay_layout.setContentsMargins(
            scaled(70, self.ui_scale),
            scaled(70, self.ui_scale),
            scaled(70, self.ui_scale),
            scaled(70, self.ui_scale),
        )
        overlay_layout.addStretch(1)
        self.maintenance_label = QLabel("")
        self.maintenance_label.setAlignment(Qt.AlignCenter)
        self.maintenance_label.setWordWrap(True)
        self.maintenance_label.setTextFormat(Qt.PlainText)
        overlay_layout.addWidget(self.maintenance_label)
        overlay_layout.addStretch(1)
        self.position_maintenance_overlay()

    def position_maintenance_overlay(self):
        if hasattr(self, "maintenance_overlay"):
            self.maintenance_overlay.setGeometry(self.rect())
            if self.maintenance_enabled:
                self.maintenance_overlay.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.position_maintenance_overlay()

    def config_file_mtime(self):
        try:
            return CONFIG_PATH.stat().st_mtime
        except Exception:
            return 0

    def refresh_runtime_config(self):
        current_mtime = self.config_file_mtime()
        if current_mtime == self.config_mtime:
            return
        try:
            updated_config = load_config()
        except Exception:
            return
        self.config = updated_config
        self.config_mtime = self.config_file_mtime()
        self.apply_maintenance_config(self.config.get("maintenance", {}))

    def apply_maintenance_config(self, maintenance):
        maintenance = maintenance if isinstance(maintenance, dict) else {}
        enabled = as_bool(maintenance.get("enabled", False))
        text = str(maintenance.get("text") or "Maintenance in progress\nPlease wait")
        background = valid_color(maintenance.get("background"), "#050505")
        foreground = valid_color(maintenance.get("foreground"), "#ffffff")
        self.maintenance_enabled = enabled
        self.maintenance_label.setText(text)
        self.maintenance_overlay.setStyleSheet(f"background-color: {background};")
        self.maintenance_label.setStyleSheet(
            f"""
            QLabel {{
                color: {foreground};
                font-size: {scaled(62, self.ui_scale)}px;
                font-weight: 900;
                letter-spacing: {scaled(1, self.ui_scale)}px;
            }}
            """
        )
        if enabled:
            if self.active_alert_dialog:
                self.active_alert_dialog.close()
                self.active_alert_dialog = None
            self.menuBar().hide()
            if self.statusBar():
                self.statusBar().hide()
            self.position_maintenance_overlay()
            self.maintenance_overlay.show()
            self.maintenance_overlay.raise_()
        else:
            self.maintenance_overlay.hide()
            self.menuBar().setVisible(not self.compact_display)
            if self.statusBar():
                self.statusBar().setVisible(not self.compact_display)
            QTimer.singleShot(0, self.show_next_alert)

    def apply_theme(self):
        scale = self.ui_scale
        table_font = scaled(14 if self.compact_display else 16, scale)
        table_padding = scaled(6 if self.compact_display else 10, scale)
        header_padding = scaled(7 if self.compact_display else 10, scale)
        header_font = scaled(13 if self.compact_display else 15, scale)
        tab_vertical_padding = scaled(8 if self.compact_display else 12, scale)
        tab_horizontal_padding = scaled(12 if self.compact_display else 20, scale)
        tab_font = scaled(13 if self.compact_display else 14, scale)
        self.setStyleSheet(
            f"""
            QMainWindow, QWidget {{ background-color: #111315; color: #f3f3f3; font-size: {scaled(14, scale)}px; }}
            QTableWidget {{ background-color: #171a1d; gridline-color: #2a2f35; alternate-background-color: #1d2126; border: 1px solid #2a2f35; border-radius: {scaled(12, scale)}px; font-size: {table_font}px; selection-background-color: #27445d; }}
            QTableWidget::item {{ padding: {table_padding}px; height: {scaled(34, scale)}px; }}
            QHeaderView::section {{ background-color: #1f252b; color: #f3f3f3; padding: {header_padding}px; border: none; border-bottom: 1px solid #2a2f35; font-size: {header_font}px; font-weight: 600; }}
            QTabWidget::pane {{ border: 1px solid #2a2f35; border-radius: {scaled(14, scale)}px; }}
            QTabBar::tab {{ background: #1a1f24; color: #dcdcdc; padding: {tab_vertical_padding}px {tab_horizontal_padding}px; border-top-left-radius: {scaled(10, scale)}px; border-top-right-radius: {scaled(10, scale)}px; font-size: {tab_font}px; font-weight: 800; }}
            QTabBar::tab:selected {{ background: #57d68d; color: #06100b; }}
            QTabBar::tab:hover {{ background: #28343d; }}
            QPushButton {{ background-color: #2b343d; color: white; padding: {scaled(10, scale)}px {scaled(14, scale)}px; border-radius: {scaled(10, scale)}px; font-size: {scaled(14, scale)}px; }}
            QPushButton:hover {{ background-color: #36424d; }}
            QPushButton#jobActionButton {{
                background-color: #f4c542;
                color: #111315;
                font-size: {scaled(18, scale)}px;
                font-weight: 800;
                padding: {scaled(14, scale)}px {scaled(18, scale)}px;
                border: 2px solid #fff0a6;
                border-radius: {scaled(8, scale)}px;
            }}
            QPushButton#jobActionButton:disabled {{
                background-color: #343a40;
                color: #8e979f;
                border: 1px solid #4a525a;
            }}
            QLabel {{ color: #f3f3f3; }}
            QLabel#sectionHeading {{ font-size: {scaled(22, scale)}px; font-weight: 700; padding: {scaled(8, scale)}px {scaled(4, scale)}px; }}
            QLabel#compactScreenLabel {{ font-size: {scaled(20, scale)}px; font-weight: 900; color: #ffffff; }}
            QLabel#compactMetaLabel {{ font-size: {scaled(12, scale)}px; font-weight: 700; color: #9fa8ad; }}
            QLabel#compactOverviewHeading {{ font-size: {scaled(24, scale)}px; font-weight: 1000; color: #ffffff; }}
            QLabel#compactOverviewSubtitle {{ font-size: {scaled(12, scale)}px; font-weight: 700; color: #aeb8bf; }}
            QLabel#alertQueueBadge {{
                background-color: #c3423f;
                color: white;
                font-size: {scaled(15, scale)}px;
                font-weight: 700;
                padding: {scaled(8, scale)}px {scaled(14, scale)}px;
                border-radius: {scaled(14, scale)}px;
            }}
            QPushButton#clearAlertsButton {{
                background-color: #793238;
                color: white;
                font-size: {scaled(15, scale)}px;
                font-weight: 800;
                padding: {scaled(8, scale)}px {scaled(14, scale)}px;
                border-radius: {scaled(14, scale)}px;
                border: 1px solid #a84a52;
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
        target = str(self.current_screen or "today").strip().lower()
        if target in {"home", "landing", "dashboard"}:
            target = "overview"
        if self.compact_display and target not in self.screen_tab_indexes:
            target = "overview"
        if target in self.screen_tab_indexes:
            self.tabs.setCurrentIndex(self.screen_tab_indexes[target])
        self.update_compact_header()

    def update_compact_header(self, refreshed_at=""):
        if not hasattr(self, "compact_screen_label"):
            return
        current_index = self.tabs.currentIndex() if hasattr(self, "tabs") else -1
        screen_title = self.tabs.tabText(current_index) if current_index >= 0 else str(self.current_screen).title()
        self.compact_screen_label.setText(screen_title)
        parts = [f"v{self.config.get('version', 'unknown')}"]
        if refreshed_at:
            parts.append(refreshed_at)
        if self.compact_layout_mode == "auto":
            parts.append("compact auto")
        else:
            parts.append(self.compact_layout_mode)
        self.compact_meta_label.setText("  |  ".join(parts))

    def poll_alerts(self):
        if self.clearing_alerts:
            return
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
        if self.clearing_alerts:
            self.pending_alerts.clear()
            self.remote_alert_queue_remaining = 0
            self.update_notification_queue_badge()
            return
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
        if self.clearing_alerts:
            self.update_notification_queue_badge()
            return
        if self.maintenance_enabled:
            self.update_notification_queue_badge()
            return
        if self.active_alert_dialog or not self.pending_alerts:
            return

        alert = self.pending_alerts.pop(0)
        self.update_notification_queue_badge()
        if alert.get("play_sound") and not alert.get("_sound_played"):
            self.play_alert_sound(alert.get("sound", ""), alert.get("_sound_path"))

        if not alert.get("show_popup", True):
            QTimer.singleShot(0, self.finish_current_alert)
            return

        total_notifications = len(self.pending_alerts) + max(0, self.remote_alert_queue_remaining) + 1
        self.active_alert_dialog = AlertDialog(
            alert.get("title", "Notification"),
            alert.get("html", ""),
            self,
            show_clear_all=total_notifications > 2,
            clear_all_callback=self.clear_all_notifications,
        )
        self.active_alert_dialog.finished.connect(self.finish_current_alert)
        self.active_alert_dialog.open()

    def finish_current_alert(self, *_args):
        self.active_alert_dialog = None
        self.update_notification_queue_badge()
        self.show_next_alert()

    def update_notification_queue_badge(self):
        queued_count = len(self.pending_alerts) + max(0, self.remote_alert_queue_remaining)
        visible_count = queued_count + (1 if self.active_alert_dialog else 0)
        self.clear_alerts_button.setVisible(visible_count > 2)
        if queued_count <= 0:
            self.alert_queue_badge.hide()
            self.alert_queue_badge.setText("")
            return
        label = "notification" if queued_count == 1 else "notifications"
        self.alert_queue_badge.setText(f"{queued_count} queued {label}")
        self.alert_queue_badge.show()

    def clear_all_notifications(self):
        self.clearing_alerts = True
        self.pending_alerts.clear()
        self.remote_alert_queue_remaining = 0
        dialog = self.active_alert_dialog
        self.active_alert_dialog = None
        if dialog:
            dialog.acknowledged = True
            dialog.accept()
        self.update_notification_queue_badge()
        Thread(target=self._clear_remote_notifications_worker, daemon=True).start()

    def _clear_remote_notifications_worker(self):
        result = {"ok": False, "cleared": 0, "error": ""}
        try:
            response = requests.post(
                self.server_url(f"/alerts/{registration_id(self.config)}/clear"),
                timeout=5,
            )
            response.raise_for_status()
            payload = response.json() if response.content else {}
            result = {"ok": True, "cleared": int(payload.get("cleared", 0) or 0), "error": ""}
        except Exception as error:
            result = {"ok": False, "cleared": 0, "error": str(error)}
        self.clear_alerts_result_ready.emit(result)

    def handle_clear_alerts_result(self, result):
        self.clearing_alerts = False
        self.pending_alerts.clear()
        self.remote_alert_queue_remaining = 0
        self.update_notification_queue_badge()
        if not result.get("ok"):
            self.report_audio_event(f"Could not clear remote notification queue: {result.get('error', '')}", level="warning")
            return
        cleared = int(result.get("cleared", 0) or 0)
        if cleared:
            self.report_audio_event(f"Cleared {cleared} queued notification(s) from this screen.")

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

    def report_audio_health(self):
        Thread(target=self._report_audio_health_worker, daemon=True).start()

    def _report_audio_health_worker(self):
        report = audio_health_report(self.config, sounds_dir=BASE_DIR / "sounds", apply_preferences=True)
        level = "info" if report.get("ok") else "warning"
        message = str(report.get("summary") or "Audio check complete.")
        detail = str(report.get("detail") or "").strip()
        if detail:
            message = f"{message}: {detail}"
        post_status(
            self.config,
            "online",
            message,
            source="audio",
            timeout=4,
            event_only=True,
            level=level,
            audio_status=report,
        )

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
        unreturned = bundle.get("unreturned", {"title": "Unreturned Jobs", "summary": {}, "rows": []})
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
        if self.compact_overview_page is not None:
            self.compact_overview_page.set_data(
                {
                    "today_out": (
                        today.get("summary", {}).get("Jobs Out", 0),
                        "collecting / delivering",
                    ),
                    "today_in": (today.get("summary", {}).get("Jobs In", 0), "returning today"),
                    "tomorrow_out": (
                        tomorrow.get("summary", {}).get("Jobs Out", 0),
                        "collecting / delivering",
                    ),
                    "tomorrow_in": (tomorrow.get("summary", {}).get("Jobs In", 0), "returning tomorrow"),
                    "prep": (f"{prepared_qty}/{total_qty}", f"{prepped_pct}% prepped"),
                    "outstanding": (
                        outstanding.get("summary", {}).get("Outstanding", 0),
                        "items awaiting check-in",
                    ),
                    "unreturned": (
                        unreturned.get("summary", {}).get("Jobs", 0),
                        "jobs in unreturned view",
                    ),
                    "quarantines": (
                        quarantine_summary.get("Total", 0),
                        quarantine_summary.get("Status", "current"),
                    ),
                }
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
            ["Job Number", "Job Name", "Booked Out", "Checked In", "Total Items", "Owner", "Action"],
            outstanding.get("rows", []),
        )
        self.add_outstanding_action_buttons()
        self.unreturned_table.set_rows(
            ["Job Name", "Job Number", "Customer Returning", "Time", "Client", "Owner", "Job Returned"],
            unreturned.get("rows", []),
        )
        if self.quarantines_table is not None:
            quarantine_detail_rows = quarantines.get("detail_rows", []) or []
            if quarantine_detail_rows:
                self.quarantines_table.set_rows(
                    ["Department", "Item", "Asset", "Reason", "Status", "Created"],
                    quarantine_detail_rows,
                )
            else:
                self.quarantines_table.set_rows(
                    ["Rank", "Department", "Quarantines", "Tag"],
                    quarantines.get("rows", []),
                )
        self.notifications_table.set_rows(
            ["Time", "Title", "Source", "Details"],
            notifications.get("rows", []),
        )
        refresh_time = __import__("datetime").datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.last_refresh.setText("Last refresh: " + refresh_time)
        self.update_compact_header(refresh_time)

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
            button.setObjectName("jobActionButton")
            button.setMinimumHeight(scaled(56, self.ui_scale))
            button.setEnabled(bool(items))
            button.clicked.connect(lambda _checked=False, row_index=row: self.open_unprepped_items_dialog(row_index, 0))
            self.prep_table.setCellWidget(row, action_col, button)

    def add_outstanding_action_buttons(self):
        try:
            action_col = self.outstanding_table.headers_for_data.index("Action")
        except ValueError:
            return

        self.outstanding_table.set_touch_row_height(scaled(74, self.ui_scale))
        self.outstanding_table.horizontalHeader().setSectionResizeMode(action_col, QHeaderView.Fixed)
        self.outstanding_table.setColumnWidth(action_col, scaled(330, self.ui_scale))

        for row in range(self.outstanding_table.rowCount()):
            data = self.outstanding_table.row_data(row)
            items = data.get("__outstanding_items", [])
            detail_qty = sum(safe_int(item.get("Outstanding"), 0) for item in items)
            row_qty = safe_int(data.get("Booked Out"), 0)
            outstanding_qty = detail_qty or row_qty
            button = QPushButton(
                f"VIEW OUTSTANDING ({outstanding_qty})" if outstanding_qty > 0 else "ALL CHECKED IN"
            )
            button.setObjectName("jobActionButton")
            button.setMinimumHeight(scaled(56, self.ui_scale))
            button.setEnabled(outstanding_qty > 0)
            button.clicked.connect(
                lambda _checked=False, row_index=row: self.open_outstanding_items_dialog(row_index, 0)
            )
            self.outstanding_table.setCellWidget(row, action_col, button)

    def open_unprepped_items_dialog(self, row, _column):
        data = self.prep_table.row_data(row)
        items = data.get("__unprepped_items", [])
        if not items:
            QMessageBox.information(self, "Prep Status", "Everything on this job is prepared.")
            return
        dlg = UnpreppedItemsDialog(data.get("Job Name", "Job"), data.get("Job Number", ""), items, self)
        dlg.exec()

    def open_outstanding_items_dialog(self, row, _column):
        data = self.outstanding_table.row_data(row)
        items = data.get("__outstanding_items", [])
        booked_out_qty = safe_int(data.get("Booked Out"), 0)
        if not items and booked_out_qty <= 0:
            QMessageBox.information(self, "Outstanding Items", "Everything on this job is checked in.")
            return
        dlg = OutstandingItemsDialog(
            data.get("Job Name", "Job"),
            data.get("Job Number", ""),
            items,
            booked_out_qty,
            self,
        )
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

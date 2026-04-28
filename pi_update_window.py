import json
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QProgressBar, QVBoxLayout, QWidget


class UpdateWindow(QMainWindow):
    def __init__(self, status_path):
        super().__init__()
        self.status_path = Path(status_path)
        self.close_timer = None
        self.has_seen_status = False
        self.last_state = ""
        self.setWindowTitle("Warehouse Dashboard Update")
        self.showFullScreen()
        self._build_ui()
        self._apply_theme()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_status)
        self.timer.start(250)
        self.refresh_status()

    def _build_ui(self):
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(80, 80, 80, 80)
        layout.setSpacing(24)

        self.heading = QLabel("Updating Warehouse Dashboard")
        self.heading.setObjectName("heading")
        self.heading.setAlignment(Qt.AlignCenter)

        self.status = QLabel("Preparing update...")
        self.status.setObjectName("status")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setWordWrap(True)

        self.detail = QLabel("Please keep this Pi powered on.")
        self.detail.setObjectName("detail")
        self.detail.setAlignment(Qt.AlignCenter)
        self.detail.setWordWrap(True)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("%p%")
        self.progress.setFixedHeight(44)

        self.footer = QLabel("Applying updates from GitHub")
        self.footer.setObjectName("footer")
        self.footer.setAlignment(Qt.AlignCenter)

        layout.addStretch(1)
        layout.addWidget(self.heading)
        layout.addWidget(self.status)
        layout.addWidget(self.detail)
        layout.addWidget(self.progress)
        layout.addWidget(self.footer)
        layout.addStretch(1)
        self.setCentralWidget(central)

    def _apply_theme(self):
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background-color: #111315;
                color: #f3f3f3;
                font-family: "Segoe UI", sans-serif;
            }
            QLabel#heading {
                font-size: 42px;
                font-weight: 700;
                color: #5bc0eb;
            }
            QLabel#status {
                font-size: 30px;
                font-weight: 600;
            }
            QLabel#detail {
                font-size: 22px;
                color: #d4d8dd;
            }
            QLabel#footer {
                font-size: 18px;
                color: #9aa4ad;
            }
            QProgressBar {
                border: 1px solid #2a2f35;
                border-radius: 14px;
                background: #171a1d;
                text-align: center;
                font-size: 18px;
                font-weight: 700;
                color: #f3f3f3;
            }
            QProgressBar::chunk {
                background-color: #3ba55d;
                border-radius: 13px;
            }
            """
        )

    def load_status(self):
        if not self.status_path.exists():
            return None
        try:
            return json.loads(self.status_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def refresh_status(self):
        payload = self.load_status()
        if not payload:
            if self.has_seen_status and self.last_state in {"complete", "failed"}:
                self.close()
            return
        self.has_seen_status = True

        title = str(payload.get("title", "")).strip() or "Updating Warehouse Dashboard"
        detail = str(payload.get("detail", "")).strip() or "Please keep this Pi powered on."
        progress = max(0, min(100, int(payload.get("progress", 0) or 0)))
        state = str(payload.get("state", "running")).strip().lower()

        self.status.setText(title)
        self.detail.setText(detail)
        self.progress.setValue(progress)

        if state != self.last_state:
            self.last_state = state
            if state == "complete":
                self.footer.setText("Update complete. Launching the latest dashboard...")
                self.schedule_close(2500)
            elif state == "failed":
                self.footer.setText("Update failed. Keeping the current dashboard version.")
                self.schedule_close(6000)
            else:
                self.footer.setText("Applying updates from GitHub")
                if self.close_timer:
                    self.close_timer.stop()
                    self.close_timer = None

    def schedule_close(self, delay_ms):
        if self.close_timer:
            self.close_timer.stop()
            self.close_timer = None
        self.close_timer = QTimer(self)
        self.close_timer.setSingleShot(True)
        self.close_timer.timeout.connect(self.close)
        self.close_timer.start(delay_ms)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: pi_update_window.py <status-file>")

    app = QApplication(sys.argv)
    window = UpdateWindow(sys.argv[1])
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()

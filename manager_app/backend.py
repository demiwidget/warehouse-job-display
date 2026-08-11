from threading import Event, Thread
import time

from manager_app.server import ServerThread
from manager_app.state import ManagerState


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
                if (settings.get("night_sleep", {}) or {}).get("enabled"):
                    interval = min(interval, 60)
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


def start_backend(state=None):
    state = state or ManagerState()
    server = ServerThread(state)
    monitor = DashboardMonitorThread(state)
    update_monitor = UpdateMonitorThread(state)
    server.start()
    monitor.start()
    update_monitor.start()
    return state, server, monitor, update_monitor


def main():
    state, _server, monitor, update_monitor = start_backend()
    state.log_activity("Manager", "Headless Manager Pi backend started.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        state.log_activity("Manager", "Headless Manager Pi backend stopping.", level="warning")
        monitor.stop_event.set()
        update_monitor.stop_event.set()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

from threading import Thread
import time
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

from manager_app.security import TOKEN_HEADER, ensure_admin_password, security_status, token_matches
from manager_app.settings_store import PROJECT_ROOT


SOUNDS_DIR = PROJECT_ROOT / "sounds"


def create_app(state):
    app = Flask(__name__)

    def is_loopback_request():
        remote_addr = str(request.remote_addr or "").strip()
        return remote_addr in {"127.0.0.1", "::1"} or remote_addr.startswith("127.")

    @app.before_request
    def require_admin_token():
        if not request.path.startswith("/api/"):
            return None
        if request.path == "/api/auth/status":
            return None
        if is_loopback_request():
            return None

        token = request.headers.get(TOKEN_HEADER, "")
        auth_header = request.headers.get("Authorization", "")
        if not token and auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
        if token_matches(token):
            return None
        return jsonify({"error": "Manager Pi admin token is required."}), 401

    @app.get("/api/auth/status")
    def auth_status():
        ensure_admin_password()
        return jsonify({"ok": True, "auth_required": True, "security": security_status()})

    @app.post("/register")
    def register():
        payload = request.get_json(silent=True) or {}
        device = state.register_device(payload, request.remote_addr)
        if not device:
            return jsonify({"error": "Device id is required."}), 400
        return jsonify({"ok": True, "device": device})

    @app.post("/status")
    def device_status():
        payload = request.get_json(silent=True) or {}
        device = state.report_device_status(payload, request.remote_addr)
        if not device:
            return jsonify({"error": "Device id is required."}), 400
        return jsonify({"ok": True, "device": device})

    @app.get("/poll/<device_id>")
    def poll(device_id):
        return jsonify(state.poll_command(device_id))

    @app.get("/alerts/<device_id>")
    def alerts(device_id):
        return jsonify(state.poll_alert(device_id))

    @app.get("/sounds/<path:filename>")
    def sounds(filename):
        safe_name = Path(str(filename or "").strip()).name
        if not safe_name or safe_name != str(filename or "").strip():
            abort(404)
        if Path(safe_name).suffix.lower() != ".wav":
            abort(404)
        if not (SOUNDS_DIR / safe_name).is_file():
            abort(404)
        return send_from_directory(
            SOUNDS_DIR,
            safe_name,
            mimetype="audio/wav",
            as_attachment=False,
            max_age=30,
        )

    @app.get("/screen/<screen>")
    def screen(screen):
        return jsonify(state.screen_payload(screen))

    @app.get("/screens")
    def screens():
        return jsonify(state.all_screen_payloads())

    @app.get("/api/devices")
    def devices():
        return jsonify(state.list_devices())

    @app.post("/api/devices/remove")
    def remove_devices():
        payload = request.get_json(silent=True) or {}
        removed = state.remove_devices(payload.get("device_ids") or [])
        return jsonify({"ok": True, "removed": removed})

    @app.get("/api/activity")
    def activity():
        return jsonify(
            state.list_activity(
                category=request.args.get("category", "All"),
                level=request.args.get("level", "All"),
                limit=request.args.get("limit", 500),
            )
        )

    @app.post("/api/activity/clear")
    def clear_activity():
        state.clear_activity()
        return jsonify({"ok": True})

    @app.get("/api/update-status")
    def update_status():
        return jsonify(state.get_update_status())

    @app.post("/api/update-status/refresh")
    def refresh_update_status():
        return jsonify(state.refresh_update_status(force=True))

    @app.post("/api/dashboard/refresh")
    def refresh_dashboard():
        state.refresh_dashboard()
        return jsonify({"ok": True})

    @app.get("/api/manager/status")
    def manager_status():
        return jsonify(state.get_manager_status())

    @app.post("/api/manager/command")
    def manager_command():
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify(state.run_manager_command(payload.get("action", "")))
        except Exception as error:
            state.log_exception("Manager", "Manager Pi command failed", error)
            return jsonify({"ok": False, "message": str(error)}), 400

    @app.post("/api/auth/password")
    def change_auth_password():
        payload = request.get_json(silent=True) or {}
        try:
            status = state.change_admin_password(
                payload.get("current_password", ""),
                payload.get("new_password", ""),
            )
            return jsonify({"ok": True, "security": status})
        except Exception as error:
            state.log_exception("Manager", "Manager Pi password change failed", error)
            return jsonify({"ok": False, "message": str(error)}), 400

    @app.post("/api/devices/command")
    def command():
        payload = request.get_json(silent=True) or {}
        device_ids = payload.get("device_ids") or []
        action = payload.get("action")
        if not device_ids or not action:
            return jsonify({"error": "device_ids and action are required."}), 400
        extras = {
            key: value
            for key, value in payload.items()
            if key not in {"device_ids", "action"}
        }
        command_payload = state.queue_command(device_ids, action, **extras)
        return jsonify({"ok": True, "command": command_payload})

    @app.get("/api/settings")
    def get_settings():
        include_secret = str(request.args.get("include_secret", "")).strip().lower() in {"1", "true", "yes"}
        return jsonify(state.get_settings(include_secret=include_secret))

    @app.post("/api/settings")
    def save_settings():
        payload = request.get_json(silent=True) or {}
        return jsonify(state.save_settings(payload))

    @app.post("/api/current-rms/test")
    def test_current_rms():
        payload = request.get_json(silent=True) or {}
        success, message = state.test_current_rms(payload)
        return jsonify({"success": success, "message": message})

    @app.post("/api/notifications/test")
    def test_notification():
        payload = request.get_json(silent=True) or {}
        success, message = state.send_test_notification(
            title=payload.get("title", ""),
            message=payload.get("message", ""),
            sound_name=payload.get("sound_name", ""),
            play_sound=payload.get("play_sound", True),
            device_ids=payload.get("device_ids"),
        )
        return jsonify({"success": success, "message": message})

    @app.post("/api/email/test")
    def test_email():
        payload = request.get_json(silent=True) or {}
        success, message = state.test_email_alerts(payload.get("alerts"))
        return jsonify({"success": success, "message": message})

    @app.post("/api/sounds/upload")
    def upload_sound():
        upload = request.files.get("file")
        if upload is None:
            return jsonify({"success": False, "message": "No sound file was uploaded."}), 400
        safe_name = Path(str(upload.filename or "").strip()).name
        if not safe_name or Path(safe_name).suffix.lower() != ".wav":
            return jsonify({"success": False, "message": "Upload a .wav sound file."}), 400
        SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
        upload.save(SOUNDS_DIR / safe_name)
        state.log_activity("Settings", f"Uploaded alert sound {safe_name}.")
        return jsonify({"success": True, "filename": safe_name})

    return app


class ServerThread(Thread):
    def __init__(self, state):
        super().__init__(daemon=True)
        self.state = state
        self.app = create_app(state)

    def run(self):
        while True:
            try:
                settings = self.state.get_settings(include_secret=True)
                server = settings.get("server", {})
                host = server.get("host", "0.0.0.0")
                port = int(server.get("port", 8765))
                self.state.log_activity("Manager", f"Manager server listening on {host}:{port}.")
                self.app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
                self.state.log_activity("Manager", "Manager server stopped.", level="warning")
                return
            except Exception as error:
                self.state.log_exception("Manager", "Manager server stopped unexpectedly", error)
                time.sleep(5)

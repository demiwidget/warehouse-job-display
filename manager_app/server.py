from threading import Thread

from flask import Flask, jsonify, request


def create_app(state):
    app = Flask(__name__)

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

    @app.get("/screen/<screen>")
    def screen(screen):
        return jsonify(state.screen_payload(screen))

    @app.get("/screens")
    def screens():
        return jsonify(state.all_screen_payloads())

    @app.get("/api/devices")
    def devices():
        return jsonify(state.list_devices())

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
        return jsonify(state.get_settings(include_secret=False))

    @app.post("/api/current-rms/test")
    def test_current_rms():
        payload = request.get_json(silent=True) or {}
        success, message = state.test_current_rms(payload)
        return jsonify({"success": success, "message": message})

    return app


class ServerThread(Thread):
    def __init__(self, state):
        super().__init__(daemon=True)
        self.state = state
        self.app = create_app(state)

    def run(self):
        settings = self.state.get_settings(include_secret=True)
        server = settings.get("server", {})
        host = server.get("host", "0.0.0.0")
        port = int(server.get("port", 8765))
        self.app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)

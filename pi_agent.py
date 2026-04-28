import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

from app_version import sync_config_version
from pi_identity import registration_id, registration_payload

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "viewer_config.json"


def load_config():
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    changed = sync_config_version(cfg)
    cfg, identity_changed, _payload = registration_payload(cfg)
    if changed or identity_changed:
        save_config(cfg)
    return cfg


def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def url(cfg, path):
    return cfg["server"].rstrip("/") + path


def register(cfg):
    try:
        _cfg, _changed, payload = registration_payload(dict(cfg))
        requests.post(
            url(cfg, "/register"),
            json=payload,
            timeout=5,
        )
    except Exception:
        pass


def run_systemctl(*args):
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return False

    command = [systemctl, *args]
    if os.name != "nt" and os.geteuid() != 0:
        sudo = shutil.which("sudo")
        if not sudo:
            return False
        command = [sudo, *command]

    try:
        subprocess.run(command, check=True, timeout=20)
        return True
    except Exception:
        return False


def start_viewer():
    env = os.environ.copy()
    env["DISPLAY"] = env.get("DISPLAY", ":0")
    env["XAUTHORITY"] = env.get("XAUTHORITY", str(Path.home() / ".Xauthority"))

    with open(str(Path.home() / "viewer.log"), "ab") as log_file:
        subprocess.Popen(
            [sys.executable, str(BASE_DIR / "pi_viewer.py")],
            stdout=log_file,
            stderr=log_file,
            env=env,
            cwd=str(BASE_DIR),
            start_new_session=True,
        )


def restart_viewer():
    display_service = os.environ.get("WAREHOUSE_DISPLAY_SERVICE", "warehouse-viewer.service")
    if run_systemctl("restart", display_service):
        return

    os.system("pkill -f pi_viewer.py || true")
    time.sleep(2)
    start_viewer()


def reboot_pi():
    reboot = shutil.which("reboot") or "/usr/sbin/reboot"
    command = [reboot]
    if os.name != "nt" and os.geteuid() != 0:
        sudo = shutil.which("sudo")
        if sudo:
            command = [sudo, reboot]

    try:
        subprocess.Popen(command, start_new_session=True)
    except Exception:
        pass


def handle_command(cfg, cmd):
    action = cmd.get("action")
    if action == "reboot":
        reboot_pi()
    elif action == "restart":
        restart_viewer()
    elif action == "rename":
        new_name = str(cmd.get("device_name", "")).strip()
        if new_name:
            cfg["device_name"] = new_name
            save_config(cfg)
            register(cfg)
            restart_viewer()
    elif action == "set_screen":
        cfg["screen"] = cmd.get("screen", cfg.get("screen", "today"))
        save_config(cfg)
        restart_viewer()


def main():
    while True:
        try:
            cfg = load_config()
            register(cfg)
            cmd = requests.get(url(cfg, f"/poll/{registration_id(cfg)}"), timeout=10).json()
            if cmd:
                handle_command(cfg, cmd)
        except Exception:
            pass
        time.sleep(10)


if __name__ == "__main__":
    main()

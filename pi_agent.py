import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

from app_version import sync_config_version
from pi_audio import sync_audio_config
from pi_identity import registration_id, registration_payload
from pi_status import post_status

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "viewer_config.json"


def load_config():
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    changed = sync_config_version(cfg)
    changed = sync_audio_config(cfg) or changed
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


def systemd_unit_exists(service_name):
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return False

    command = [systemctl, "show", service_name, "--property=LoadState", "--value"]
    if os.name != "nt" and os.geteuid() != 0:
        sudo = shutil.which("sudo")
        if not sudo:
            return False
        command = [sudo, *command]

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
            text=True,
        )
        load_state = str(result.stdout or "").strip().lower()
        return bool(load_state) and load_state != "not-found"
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


def restart_viewer(cfg=None, reason="Restarting display app.", state="display_restarting"):
    if cfg:
        post_status(cfg, state, reason, source="agent", timeout=3)
    display_service = os.environ.get("WAREHOUSE_DISPLAY_SERVICE", "warehouse-viewer.service")
    if run_systemctl("restart", display_service):
        return

    if systemd_unit_exists(display_service):
        return

    os.system("pkill -f pi_viewer.py || true")
    time.sleep(2)
    start_viewer()


def reboot_pi(cfg=None):
    if cfg:
        post_status(cfg, "rebooting", "Rebooting Pi.", source="agent", timeout=3)
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
        reboot_pi(cfg)
    elif action == "restart":
        restart_viewer(cfg, "Restarting display app.")
    elif action == "rename":
        new_name = str(cmd.get("device_name", "")).strip()
        if new_name:
            cfg["device_name"] = new_name
            save_config(cfg)
            register(cfg)
            restart_viewer(cfg, f"Restarting display app after rename to {new_name}.", state="renaming")
    elif action == "set_screen":
        new_screen = str(cmd.get("screen", cfg.get("screen", "today"))).strip() or cfg.get("screen", "today")
        cfg["screen"] = new_screen
        save_config(cfg)
        restart_viewer(cfg, f"Restarting display app on {new_screen.title()} screen.", state="switching_screen")


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

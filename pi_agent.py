import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "viewer_config.json"
UPDATE_SCRIPT = BASE_DIR / "scripts" / "update_pi.sh"


def load_config():
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def url(cfg, path):
    return cfg["server"].rstrip("/") + path


def register(cfg):
    try:
        requests.post(
            url(cfg, "/register"),
            json={
                "id": cfg["device_id"],
                "name": cfg["device_name"],
                "screen": cfg.get("screen", "today"),
                "version": cfg.get("version", "1.0.0"),
            },
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


def trigger_git_update():
    refresh_service = os.environ.get("WAREHOUSE_REFRESH_SERVICE", "warehouse-refresh.service")
    if run_systemctl("start", refresh_service):
        return True

    if UPDATE_SCRIPT.exists():
        try:
            subprocess.Popen(
                ["bash", str(UPDATE_SCRIPT), "--restart-display"],
                cwd=str(BASE_DIR),
                start_new_session=True,
            )
            return True
        except Exception:
            return False

    return False


def apply_legacy_zip_update(cfg, filename):
    package_url = url(cfg, f"/updates/{filename}")
    tmp_zip = Path.home() / "warehouse_update.zip"
    tmp_dir = Path.home() / "warehouse_update_extract"

    response = requests.get(package_url, timeout=30)
    response.raise_for_status()
    tmp_zip.write_bytes(response.content)

    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(tmp_zip, "r") as package:
        package.extractall(tmp_dir)

    for name in ("pi_viewer.py", "pi_agent.py"):
        src = tmp_dir / name
        if src.exists():
            shutil.copy2(src, BASE_DIR / name)

    version_file = tmp_dir / "version.txt"
    if version_file.exists():
        cfg["version"] = version_file.read_text(encoding="utf-8").strip()
        save_config(cfg)

    restart_viewer()


def handle_command(cfg, cmd):
    action = cmd.get("action")
    if action == "reboot":
        os.system("sudo reboot")
    elif action == "restart":
        restart_viewer()
    elif action == "set_screen":
        cfg["screen"] = cmd.get("screen", cfg.get("screen", "today"))
        save_config(cfg)
        restart_viewer()
    elif action == "update":
        if trigger_git_update():
            return

        filename = cmd.get("filename")
        if filename:
            apply_legacy_zip_update(cfg, filename)


def main():
    while True:
        try:
            cfg = load_config()
            register(cfg)
            cmd = requests.get(url(cfg, f"/poll/{cfg['device_id']}"), timeout=10).json()
            if cmd:
                handle_command(cfg, cmd)
        except Exception:
            pass
        time.sleep(10)


if __name__ == "__main__":
    main()

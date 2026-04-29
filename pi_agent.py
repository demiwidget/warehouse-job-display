import json
import os
import shutil
import subprocess
import sys
from tempfile import NamedTemporaryFile
import time
from pathlib import Path
from threading import Thread

import requests

from app_version import sync_config_version
from pi_audio import sync_audio_config
from pi_identity import registration_id, registration_payload
from pi_status import post_status

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "viewer_config.json"


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


def load_config():
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    changed = sync_config_version(cfg)
    changed = sync_audio_config(cfg) or changed
    cfg, identity_changed, _payload = registration_payload(cfg)
    if changed or identity_changed:
        save_config(cfg)
    return cfg


def save_config(cfg):
    write_json_atomic(CONFIG_FILE, cfg)


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


def systemctl_service_details(service_name):
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return {}

    try:
        result = subprocess.run(
            [
                systemctl,
                "show",
                service_name,
                "--property=ActiveState",
                "--property=Result",
                "--property=ExecMainStatus",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
            text=True,
        )
    except Exception:
        return {}

    details = {}
    for line in str(result.stdout or "").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        details[key] = value
    return details


def systemctl_is_active(service_name):
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return False

    try:
        result = subprocess.run(
            [systemctl, "is-active", "--quiet", service_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        return result.returncode == 0
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

    pkill = shutil.which("pkill")
    if pkill:
        subprocess.run(
            [pkill, "-f", "pi_viewer.py"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
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


def monitor_update_service(cfg, service_name):
    time.sleep(3)
    deadline = time.time() + 300
    while time.time() < deadline:
        if not systemctl_is_active(service_name):
            details = systemctl_service_details(service_name)
            result = str(details.get("Result", "")).strip().lower()
            exit_status = str(details.get("ExecMainStatus", "")).strip()
            if result and result != "success":
                post_status(
                    cfg,
                    "update_failed",
                    f"Update service stopped with result {result} and exit status {exit_status or 'unknown'}.",
                    source="agent",
                    timeout=3,
                )
                return
            post_status(
                cfg,
                "online",
                "Update check complete. No display restart was needed.",
                source="agent",
                timeout=3,
            )
            return
        time.sleep(3)

    post_status(
        cfg,
        "updating",
        "Update is still running. Check the Pi if this message stays for too long.",
        source="agent",
        timeout=3,
    )


def start_update_process(cfg):
    post_status(cfg, "updating", "Checking GitHub for Pi updates.", source="agent", timeout=3)

    update_service = os.environ.get("WAREHOUSE_UPDATE_SERVICE", "warehouse-update.service")
    if systemd_unit_exists(update_service):
        if run_systemctl("--no-block", "start", update_service):
            Thread(target=monitor_update_service, args=(dict(cfg), update_service), daemon=True).start()
            return

        post_status(
            cfg,
            "update_failed",
            "Could not start the Pi update service. Re-run the Pi installer to refresh permissions.",
            source="agent",
            timeout=3,
        )
        return

    script = BASE_DIR / "scripts" / "update_pi.sh"
    if not script.exists():
        post_status(cfg, "update_failed", "Updater script is missing on this Pi.", source="agent", timeout=3)
        return

    try:
        log_path = Path.home() / "warehouse-update.log"
        with log_path.open("ab") as log_file:
            subprocess.Popen(
                [str(script)],
                stdout=log_file,
                stderr=log_file,
                cwd=str(BASE_DIR),
                start_new_session=True,
            )
    except Exception:
        post_status(cfg, "update_failed", "Could not start the Pi updater.", source="agent", timeout=3)


def handle_command(cfg, cmd):
    action = cmd.get("action")
    if action == "reboot":
        reboot_pi(cfg)
    elif action == "restart":
        restart_viewer(cfg, "Restarting display app.")
    elif action == "update":
        start_update_process(cfg)
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

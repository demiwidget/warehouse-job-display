import json
import os
import signal
import shutil
import subprocess
import sys
from tempfile import NamedTemporaryFile
import time
from pathlib import Path
from threading import Thread

import requests

from app_version import sync_config_version
from pi_audio import audio_health_report, audio_runtime_environment, normalize_audio_volume, sync_audio_config
from pi_identity import normalize_display_scale, registration_id, registration_payload
from pi_status import post_status

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "viewer_config.json"
SOUND_LOOP_PID_FILE = Path("/tmp/warehouse-dashboard-sound-loop.pid")
DEFAULT_LOOP_SOUND = "job-changes.wav"


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


def audio_status_payload(cfg, apply_preferences=False):
    return audio_health_report(cfg, sounds_dir=BASE_DIR / "sounds", apply_preferences=apply_preferences)


def post_audio_status(cfg, apply_preferences=False, source="agent"):
    report = audio_status_payload(cfg, apply_preferences=apply_preferences)
    level = "info" if report.get("ok") else "warning"
    message = str(report.get("summary") or "Audio check complete.")
    detail = str(report.get("detail") or "").strip()
    if detail:
        message = f"{message}: {detail}"
    post_status(
        cfg,
        "online",
        message,
        source=source,
        timeout=5,
        event_only=True,
        level=level,
        audio_status=report,
    )
    return report


def safe_sound_name(sound_name):
    raw_name = str(sound_name or "").strip() or DEFAULT_LOOP_SOUND
    if "/" in raw_name or "\\" in raw_name:
        return ""
    safe_name = Path(raw_name).name
    if safe_name != raw_name or Path(safe_name).suffix.lower() != ".wav":
        return ""
    return safe_name


def sound_player_command(sound_path):
    for binary, command in (
        ("pw-play", ["pw-play", str(sound_path)]),
        ("paplay", ["paplay", str(sound_path)]),
        ("aplay", ["aplay", "-q", str(sound_path)]),
    ):
        if shutil.which(binary):
            return binary, command
    return "", []


def sound_loop_main(sound_path, interval_seconds=2.0):
    sound_path = Path(sound_path)
    while SOUND_LOOP_PID_FILE.exists():
        _player, command = sound_player_command(sound_path)
        if not command:
            time.sleep(interval_seconds)
            continue
        try:
            subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
                env=audio_runtime_environment(),
            )
        except Exception:
            pass
        time.sleep(interval_seconds)


def stop_sound_loop(cfg=None, report=True):
    stopped = False
    try:
        pid = int(SOUND_LOOP_PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        pid = None

    try:
        SOUND_LOOP_PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    if pid:
        try:
            os.killpg(pid, signal.SIGTERM)
            stopped = True
        except Exception:
            try:
                os.kill(pid, signal.SIGTERM)
                stopped = True
            except Exception:
                pass

    if cfg and report:
        message = "Stopped repeating sound check." if stopped else "Repeating sound check was not running."
        post_status(cfg, "online", message, source="audio", timeout=3, event_only=True, level="info")
    return stopped


def start_sound_loop(cfg, sound_name=None):
    safe_name = safe_sound_name(sound_name)
    if not safe_name:
        post_status(
            cfg,
            "online",
            f"Could not start repeating sound check: invalid sound file {sound_name}.",
            source="audio",
            timeout=3,
            event_only=True,
            level="warning",
        )
        return False

    sound_path = BASE_DIR / "sounds" / safe_name
    if not sound_path.exists():
        post_status(
            cfg,
            "online",
            f"Could not start repeating sound check: {safe_name} is missing on this Pi.",
            source="audio",
            timeout=3,
            event_only=True,
            level="warning",
        )
        return False

    stop_sound_loop(report=False)
    report = post_audio_status(cfg, apply_preferences=True, source="audio")
    if not report.get("ok"):
        return False

    _player, command = sound_player_command(sound_path)
    if not command:
        post_status(
            cfg,
            "online",
            "Could not start repeating sound check: no WAV player found.",
            source="audio",
            timeout=3,
            event_only=True,
            level="warning",
        )
        return False

    try:
        SOUND_LOOP_PID_FILE.write_text("starting", encoding="utf-8")
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--sound-loop", str(sound_path), "2"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(BASE_DIR),
            start_new_session=True,
        )
        SOUND_LOOP_PID_FILE.write_text(str(process.pid), encoding="utf-8")
        time.sleep(0.5)
        if process.poll() is not None:
            try:
                SOUND_LOOP_PID_FILE.unlink(missing_ok=True)
            except Exception:
                pass
            post_status(
                cfg,
                "online",
                f"Repeating sound check stopped immediately using {safe_name}.",
                source="audio",
                timeout=3,
                event_only=True,
                level="warning",
            )
            return False
    except Exception as error:
        post_status(
            cfg,
            "online",
            f"Could not start repeating sound check: {error}",
            source="audio",
            timeout=3,
            event_only=True,
            level="warning",
        )
        try:
            SOUND_LOOP_PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        return False

    post_status(
        cfg,
        "online",
        f"Started repeating sound check using {safe_name}. Use Stop Repeating Sound when finished.",
        source="audio",
        timeout=3,
        event_only=True,
        level="info",
    )
    return True


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
    elif action == "sound_check":
        post_audio_status(cfg, apply_preferences=True, source="audio")
    elif action == "sound_loop_start":
        start_sound_loop(cfg, cmd.get("sound_name", DEFAULT_LOOP_SOUND))
    elif action == "sound_loop_stop":
        stop_sound_loop(cfg)
    elif action == "set_audio":
        output = str(cmd.get("audio_output", cfg.get("audio_output", "hdmi"))).strip().lower()
        if output not in {"auto", "hdmi", "analog"}:
            output = "hdmi"
        cfg["audio_output"] = output
        cfg["audio_volume"] = normalize_audio_volume(cmd.get("audio_volume", cfg.get("audio_volume", 100)))
        save_config(cfg)
        post_audio_status(cfg, apply_preferences=True, source="audio")
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
    elif action == "set_display_scale":
        new_scale = normalize_display_scale(cmd.get("display_scale", cfg.get("display_scale", 100)))
        cfg["display_scale"] = new_scale
        save_config(cfg)
        register(cfg)
        restart_viewer(cfg, f"Restarting display app at {new_scale}% display size.", state="display_restarting")


def main():
    last_audio_check_at = 0
    while True:
        try:
            cfg = load_config()
            now = time.monotonic()
            register(cfg)
            if now - last_audio_check_at > 300:
                post_audio_status(cfg, apply_preferences=True, source="audio")
                last_audio_check_at = now
            cmd = requests.get(url(cfg, f"/poll/{registration_id(cfg)}"), timeout=10).json()
            if cmd:
                handle_command(cfg, cmd)
        except Exception:
            pass
        time.sleep(10)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--sound-loop":
        try:
            interval = float(sys.argv[3]) if len(sys.argv) >= 4 else 2.0
        except Exception:
            interval = 2.0
        sound_loop_main(sys.argv[2], interval)
        raise SystemExit(0)
    main()

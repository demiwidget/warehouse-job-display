import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple


DEFAULT_AUDIO_OUTPUT = "hdmi"
DEFAULT_AUDIO_VOLUME = 100

# wpctl draws sink rows with unicode tree characters on Raspberry Pi OS.
# Ignore all prefix drawing characters and capture the optional default marker.
_SINK_LINE_RE = re.compile(r"^[^\d*]*(\*)?\s*(\d+)\.\s+(.+?)(?:\s+\[vol:.*\])?\s*$")


def normalize_audio_volume(value) -> int:
    try:
        volume = int(float(value))
    except Exception:
        volume = DEFAULT_AUDIO_VOLUME
    return max(0, min(100, volume))


def sync_audio_config(cfg: Dict) -> bool:
    changed = False

    output = str(cfg.get("audio_output", "")).strip().lower()
    if output not in {"hdmi", "analog", "auto"}:
        cfg["audio_output"] = DEFAULT_AUDIO_OUTPUT
        changed = True

    volume = normalize_audio_volume(cfg.get("audio_volume", DEFAULT_AUDIO_VOLUME))
    if cfg.get("audio_volume") != volume:
        cfg["audio_volume"] = volume
        changed = True

    return changed


def _extract_sinks(status_output: str) -> List[Dict[str, object]]:
    sinks: List[Dict[str, object]] = []
    in_sinks = False

    for raw_line in status_output.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.endswith("Sinks:"):
            in_sinks = True
            continue

        if not in_sinks:
            continue

        if "Sink endpoints:" in stripped or "Sources:" in stripped or stripped == "Video":
            break

        match = _SINK_LINE_RE.match(line)
        if not match:
            continue

        sinks.append(
            {
                "default": bool(match.group(1)),
                "id": int(match.group(2)),
                "name": match.group(3).strip(),
            }
        )

    return sinks


def _sink_matches_preference(sink_name: str, preference: str) -> bool:
    name = sink_name.lower()
    if preference == "hdmi":
        return "hdmi" in name
    if preference == "analog":
        return any(token in name for token in ("analog", "headphone", "headphones", "line out", "line-out"))
    return True


def choose_sink(sinks: List[Dict[str, object]], preference: str) -> Optional[Dict[str, object]]:
    if not sinks:
        return None

    pref = str(preference or DEFAULT_AUDIO_OUTPUT).strip().lower()
    if pref == "auto":
        for sink in sinks:
            if bool(sink.get("default")):
                return sink
        return sinks[0]

    for sink in sinks:
        if _sink_matches_preference(str(sink.get("name", "")), pref):
            return sink

    for sink in sinks:
        if bool(sink.get("default")):
            return sink

    return sinks[0]


def audio_runtime_environment() -> Dict[str, str]:
    env = os.environ.copy()
    try:
        uid = os.getuid()
    except Exception:
        uid = None

    if uid is not None:
        runtime_dir = Path(f"/run/user/{uid}")
        if runtime_dir.exists():
            env.setdefault("XDG_RUNTIME_DIR", str(runtime_dir))
            bus_path = runtime_dir / "bus"
            if bus_path.exists():
                env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={bus_path}")
            pulse_path = runtime_dir / "pulse" / "native"
            if pulse_path.exists():
                env.setdefault("PULSE_SERVER", f"unix:{pulse_path}")
            if (runtime_dir / "wayland-0").exists():
                env.setdefault("WAYLAND_DISPLAY", "wayland-0")

    env.setdefault("DISPLAY", ":0")
    return env


def _compact_process_error(text: str) -> str:
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in str(text or "").splitlines()
        if line.strip()
    ]
    if not lines:
        return ""

    for line in reversed(lines):
        lowered = line.lower()
        if "could not connect" in lowered or "failed" in lowered or "unable" in lowered:
            return line[:240]
    return " ".join(lines)[-240:]


def _run_wpctl(args: List[str]) -> bool:
    wpctl = shutil.which("wpctl")
    if not wpctl:
        return False

    try:
        subprocess.run(
            [wpctl, *args],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            env=audio_runtime_environment(),
        )
        return True
    except Exception:
        return False


def _run_capture(command: List[str], timeout=10):
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=audio_runtime_environment(),
        )
    except Exception:
        return None


def _wpctl_volume() -> Dict[str, object]:
    wpctl = shutil.which("wpctl")
    if not wpctl:
        return {"volume": "", "muted": False}

    result = _run_capture([wpctl, "get-volume", "@DEFAULT_AUDIO_SINK@"], timeout=5)
    text = str(result.stdout if result else "").strip()
    muted = "[MUTED]" in text.upper()
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
    percent = ""
    if match:
        try:
            percent = int(round(float(match.group(1)) * 100))
        except Exception:
            percent = ""
    return {"volume": percent, "muted": muted, "raw": text}


def audio_health_report(cfg: Dict, sounds_dir=None, apply_preferences=False) -> Dict[str, object]:
    report: Dict[str, object] = {
        "ok": False,
        "state": "unknown",
        "summary": "Audio check has not run.",
        "detail": "",
        "configured_output": str(cfg.get("audio_output", DEFAULT_AUDIO_OUTPUT)),
        "configured_volume": normalize_audio_volume(cfg.get("audio_volume", DEFAULT_AUDIO_VOLUME)),
        "wpctl_available": bool(shutil.which("wpctl")),
        "players": [binary for binary in ("pw-play", "paplay", "aplay") if shutil.which(binary)],
        "sound_files": [],
    }

    if sounds_dir is not None:
        try:
            report["sound_files"] = sorted(path.name for path in Path(sounds_dir).glob("*.wav"))
        except Exception:
            report["sound_files"] = []

    if apply_preferences:
        applied, message = apply_audio_preferences(cfg)
        report["apply_ok"] = applied
        report["apply_message"] = message

    wpctl = shutil.which("wpctl")
    if not wpctl:
        report.update(
            {
                "state": "missing_wpctl",
                "summary": "Audio tools missing",
                "detail": "wpctl is not installed or not available to the dashboard user.",
            }
        )
        return report

    result = _run_capture([wpctl, "status"], timeout=10)
    if not result or result.returncode != 0:
        detail = _compact_process_error(result.stderr if result else "") or "wpctl status failed."
        report.update(
            {
                "state": "wpctl_failed",
                "summary": "Could not read audio status",
                "detail": detail,
            }
        )
        return report

    sinks = _extract_sinks(result.stdout)
    default_sink = next((sink for sink in sinks if bool(sink.get("default"))), None)
    preferred_sink = choose_sink(sinks, str(cfg.get("audio_output", DEFAULT_AUDIO_OUTPUT)))
    volume = _wpctl_volume()

    report.update(
        {
            "sinks": sinks,
            "sink_count": len(sinks),
            "default_sink": default_sink or {},
            "preferred_sink": preferred_sink or {},
            "volume": volume.get("volume", ""),
            "muted": bool(volume.get("muted")),
            "volume_raw": volume.get("raw", ""),
        }
    )

    if not sinks:
        report.update({"state": "no_sink", "summary": "No audio output found", "detail": "wpctl reported no audio sinks."})
        return report

    sink_name = str((default_sink or preferred_sink or {}).get("name", "")).strip()
    if "dummy output" in sink_name.lower():
        report.update(
            {
                "state": "dummy_output",
                "summary": "Audio is using Dummy Output",
                "detail": "The Pi has no real HDMI/analog audio sink selected.",
            }
        )
        return report

    preferred_name = str((preferred_sink or {}).get("name", "")).strip()
    configured_output = str(cfg.get("audio_output", DEFAULT_AUDIO_OUTPUT)).strip().lower()
    if configured_output in {"hdmi", "analog"} and preferred_sink and not _sink_matches_preference(preferred_name, configured_output):
        report.update(
            {
                "state": "wrong_output",
                "summary": "Preferred audio output not found",
                "detail": f"Configured for {configured_output}, current sink is {sink_name or preferred_name}.",
            }
        )
        return report

    if bool(volume.get("muted")):
        report.update({"state": "muted", "summary": "Audio is muted", "detail": f"Current sink: {sink_name}."})
        return report

    volume_percent = volume.get("volume")
    if isinstance(volume_percent, int) and volume_percent <= 0:
        report.update({"state": "volume_zero", "summary": "Audio volume is 0%", "detail": f"Current sink: {sink_name}."})
        return report

    if not report["players"]:
        report.update(
            {
                "state": "no_player",
                "summary": "No WAV player found",
                "detail": "None of pw-play, paplay, or aplay are available.",
            }
        )
        return report

    if sounds_dir is not None and not report["sound_files"]:
        report.update(
            {
                "state": "no_sounds",
                "summary": "No local sound files",
                "detail": "The Pi sounds folder has no .wav files yet. Sounds can still download when an alert arrives.",
            }
        )
        return report

    detail_parts = [f"Sink: {sink_name or preferred_name or 'unknown'}"]
    if isinstance(volume_percent, int):
        detail_parts.append(f"Volume: {volume_percent}%")
    detail_parts.append(f"Players: {', '.join(report['players'])}")
    report.update(
        {
            "ok": True,
            "state": "ok",
            "summary": "Audio OK",
            "detail": " | ".join(detail_parts),
        }
    )
    return report


def apply_audio_preferences(cfg: Dict) -> Tuple[bool, str]:
    wpctl = shutil.which("wpctl")
    if not wpctl:
        return False, "wpctl not available"

    result = _run_capture([wpctl, "status"], timeout=10)
    if not result or result.returncode != 0:
        return False, _compact_process_error(result.stderr if result else "") or "unable to read audio sinks"

    sinks = _extract_sinks(result.stdout)
    sink = choose_sink(sinks, str(cfg.get("audio_output", DEFAULT_AUDIO_OUTPUT)))
    if not sink:
        return False, "no audio sinks found"

    volume = normalize_audio_volume(cfg.get("audio_volume", DEFAULT_AUDIO_VOLUME)) / 100.0
    sink_id = str(sink["id"])
    sink_name = str(sink["name"])

    if not _run_wpctl(["set-default", sink_id]):
        return False, f"failed to select {sink_name}"

    _run_wpctl(["set-mute", "@DEFAULT_AUDIO_SINK@", "0"])
    _run_wpctl(["set-volume", "@DEFAULT_AUDIO_SINK@", f"{volume:.2f}"])
    return True, sink_name

import re
import shutil
import subprocess
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
        pref = DEFAULT_AUDIO_OUTPUT

    for sink in sinks:
        if _sink_matches_preference(str(sink.get("name", "")), pref):
            return sink

    for sink in sinks:
        if bool(sink.get("default")):
            return sink

    return sinks[0]


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
        )
        return True
    except Exception:
        return False


def apply_audio_preferences(cfg: Dict) -> Tuple[bool, str]:
    wpctl = shutil.which("wpctl")
    if not wpctl:
        return False, "wpctl not available"

    try:
        result = subprocess.run(
            [wpctl, "status"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return False, "unable to read audio sinks"

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

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
VERSION_FILE = BASE_DIR / "version.txt"
FALLBACK_VERSION = "2.0.92"


def read_current_version():
    try:
        version = VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return FALLBACK_VERSION
    return version or FALLBACK_VERSION


CURRENT_VERSION = read_current_version()


def sync_config_version(cfg):
    current = str(cfg.get("version", "")).strip()
    if current == CURRENT_VERSION:
        return False
    cfg["version"] = CURRENT_VERSION
    return True

#!/usr/bin/env python3
import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from pi_os_update import current_boot_id, os_release_details, parse_apt_simulation


STATUS_FILE = Path("/var/lib/warehouse-dashboard/os-update-status.json")
LOG_FILE = Path("/var/lib/warehouse-dashboard/os-update.log")
LOCK_FILE = Path("/run/lock/warehouse-os-update.lock")
MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024
MAX_PACKAGE_NAMES = 60


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def safe_text(value, limit=600):
    return str(value or "").strip()[:limit]


def write_status(**updates):
    try:
        current = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        current = {}
    if not isinstance(current, dict):
        current = {}
    current.update(updates)
    current.update(os_release_details())
    current["supported"] = True
    current["updated_at"] = now_iso()
    try:
        current["free_bytes"] = shutil.disk_usage("/").free
    except OSError:
        current["free_bytes"] = 0

    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=STATUS_FILE.parent,
        prefix=".os-update-status.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        json.dump(current, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    temp_path.chmod(0o644)
    temp_path.replace(STATUS_FILE)
    return current


def log(message):
    line = f"{now_iso()} {safe_text(message, 2000)}"
    print(f"[warehouse-os-update] {message}", flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def run(command, timeout, capture=True):
    env = os.environ.copy()
    env.update(
        {
            "LC_ALL": "C",
            "LANG": "C",
            "DEBIAN_FRONTEND": "noninteractive",
            "NEEDRESTART_MODE": "a",
        }
    )
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )
    output = str(result.stdout or "")
    if output:
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(output.rstrip() + "\n")
    if result.returncode != 0:
        tail = " ".join(output.strip().splitlines()[-4:])
        raise RuntimeError(tail or f"Command failed with exit code {result.returncode}.")
    return output


def apt_command(*args):
    apt_get = shutil.which("apt-get") or "/usr/bin/apt-get"
    return [apt_get, "-o", "DPkg::Lock::Timeout=300", *args]


def refresh_package_lists():
    write_status(progress=8, state="checking", title="Refreshing package lists", detail="Contacting Raspberry Pi OS repositories.")
    log("Refreshing package lists.")
    run(apt_command("update"), timeout=1800)


def inspect_updates(mode):
    write_status(progress=25, state="checking", title="Checking available updates", detail="Calculating a safe full upgrade.")
    output = run(apt_command("-s", "full-upgrade"), timeout=900)
    packages, removals = parse_apt_simulation(output)
    write_status(
        mode=mode,
        pending_count=len(packages),
        packages=packages[:MAX_PACKAGE_NAMES],
        removal_count=len(removals),
        removals=removals[:MAX_PACKAGE_NAMES],
    )
    return packages, removals


def check_only():
    refresh_package_lists()
    packages, removals = inspect_updates("check")
    if removals:
        write_status(
            progress=100,
            state="attention",
            title="Manual review required",
            detail=f"{len(removals)} package removal(s) would be required. Update locally before using remote install.",
            finished_at=now_iso(),
        )
        return 2
    if packages:
        write_status(
            progress=100,
            state="available",
            title="OS updates available",
            detail=f"{len(packages)} package update(s) are ready to install.",
            finished_at=now_iso(),
        )
    else:
        write_status(
            progress=100,
            state="current",
            title="Raspberry Pi OS is current",
            detail="No package updates are currently available.",
            finished_at=now_iso(),
        )
    return 0


def install_updates():
    free_bytes = shutil.disk_usage("/").free
    if free_bytes < MIN_FREE_BYTES:
        write_status(
            progress=100,
            state="attention",
            title="Not enough free space",
            detail="At least 2 GB of free storage is required before a remote OS update.",
            finished_at=now_iso(),
        )
        return 2

    write_status(progress=4, state="preparing", title="Preparing OS update", detail="Checking the package manager before installation.")
    run([shutil.which("dpkg") or "/usr/bin/dpkg", "--configure", "-a"], timeout=1800)
    refresh_package_lists()
    packages, removals = inspect_updates("install")
    if removals:
        write_status(
            progress=100,
            state="attention",
            title="Manual review required",
            detail=f"Stopped safely because {len(removals)} package removal(s) would be required.",
            finished_at=now_iso(),
        )
        return 2
    if not packages:
        write_status(
            progress=100,
            state="complete",
            title="Raspberry Pi OS is current",
            detail="No package updates were required.",
            pending_count=0,
            updated_count=0,
            reboot_required=False,
            finished_at=now_iso(),
        )
        return 0

    write_status(
        progress=35,
        state="updating",
        title="Installing OS updates",
        detail=f"Installing {len(packages)} package update(s). Do not switch off this Pi.",
    )
    log(f"Installing {len(packages)} package update(s).")
    run(
        apt_command(
            "-y",
            "--no-remove",
            "-o",
            "Dpkg::Options::=--force-confold",
            "full-upgrade",
        ),
        timeout=10800,
    )
    write_status(progress=92, state="finalising", title="Finalising OS update", detail="Checking installed packages and preparing a restart.")
    audit_output = run([shutil.which("dpkg") or "/usr/bin/dpkg", "--audit"], timeout=300)
    if audit_output.strip():
        raise RuntimeError("Package verification reported unfinished package configuration.")

    write_status(
        progress=100,
        state="complete",
        title="OS update complete",
        detail=f"Installed {len(packages)} package update(s). The Pi will restart automatically.",
        pending_count=0,
        updated_count=len(packages),
        reboot_required=True,
        finished_at=now_iso(),
    )
    log("OS update completed successfully.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Warehouse dashboard Raspberry Pi OS updater")
    parser.add_argument("mode", choices=("check", "install"))
    args = parser.parse_args()

    if os.geteuid() != 0:
        print("This updater must run as root.", file=sys.stderr)
        return 1
    if not shutil.which("apt-get"):
        print("apt-get is not available on this system.", file=sys.stderr)
        return 1

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("w", encoding="utf-8") as lock_handle:
        try:
            fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another OS update operation is already running.", file=sys.stderr)
            return 2

        started_at = now_iso()
        write_status(
            state="checking" if args.mode == "check" else "preparing",
            progress=1,
            title="Starting OS update check" if args.mode == "check" else "Starting OS update",
            detail="Initialising the secure Raspberry Pi OS update service.",
            mode=args.mode,
            pending_count=0,
            packages=[],
            removal_count=0,
            removals=[],
            reboot_required=False,
            boot_id=current_boot_id(),
            started_at=started_at,
            finished_at="",
            error="",
        )
        try:
            return check_only() if args.mode == "check" else install_updates()
        except Exception as error:
            log(f"OS update failed: {error}")
            write_status(
                progress=100,
                state="failed",
                title="OS update failed",
                detail=safe_text(error),
                error=safe_text(error, 1200),
                finished_at=now_iso(),
            )
            return 1


if __name__ == "__main__":
    raise SystemExit(main())

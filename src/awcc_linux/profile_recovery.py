"""Shared PPD recovery primitives, independent of GTK and privilege level."""
from __future__ import annotations

import subprocess
import time
import fcntl
import os
import stat
from pathlib import Path
from typing import Callable


PLATFORM_TO_DAEMON = {"low-power": "power-saver", "balanced": "balanced", "performance": "performance"}
DAEMON_TO_PLATFORM = {value: key for key, value in PLATFORM_TO_DAEMON.items()}
VERIFICATION_DELAYS = (0.0, 0.4, 0.6, 1.0)
SINGLETON = Path("/run/awcc-x17r1-native-boost.lock")


def acquire_singleton(path: Path = SINGLETON) -> int:
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid() or stat.S_IMODE(meta.st_mode) & 0o077:
            raise RuntimeError("Unsafe shared hardware lock.")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        os.close(fd)
        raise
    return fd


def daemon_profile(run: Callable = subprocess.run) -> str:
    result = run(["powerprofilesctl", "get"], capture_output=True, text=True, timeout=5, check=False)
    if result.returncode != 0 or result.stdout.strip() not in DAEMON_TO_PLATFORM:
        raise RuntimeError(result.stderr.strip() or "Không đọc được power profile hiện tại.")
    return result.stdout.strip()


def verify_routes(daemon: str, platform: str, reader: Callable,
                  run: Callable = subprocess.run, sleep: Callable = time.sleep) -> tuple[bool, str | None]:
    final = None
    stable = True
    for delay in VERIFICATION_DELAYS:
        if delay:
            sleep(delay)
        observed = daemon_profile(run)
        final = reader()
        stable = stable and observed == daemon and final == platform
    return stable, final


def restore_daemon(daemon: str, platform: str, reader: Callable,
                   run: Callable = subprocess.run, sleep: Callable = time.sleep) -> tuple[bool, str | None]:
    def attempt(target: str, physical: str) -> tuple[bool, str | None]:
        try:
            run(["powerprofilesctl", "set", target], capture_output=True, text=True, timeout=20, check=False)
        except subprocess.TimeoutExpired:
            # The D-Bus request may have completed even when the CLI timed out.
            pass
        return verify_routes(target, physical, reader, run, sleep)

    stable, final = attempt(daemon, platform)
    if not stable and daemon != "balanced" and daemon_profile(run) == daemon:
        # A same-value PPD Set can leave a nonstandard physical profile in place.
        bridge, final = attempt("balanced", "balanced")
        if bridge:
            return attempt(daemon, platform)
    return stable, final

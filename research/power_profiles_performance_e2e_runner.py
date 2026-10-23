#!/usr/bin/python3
"""One end-to-end Performance check through the app's PPD command path.

The desktop application invokes ``powerprofilesctl`` for Performance.  This
runner exercises that exact command as the invoking desktop user, observes both
PPD and platform-profile over the app's two-second window, then restores
Balanced.  An independent watchdog uses the same command if the parent exits.
"""
from __future__ import annotations

import fcntl
import glob
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time


CONFIRM_FLAG = "--confirm-x17r1-performance-ppd-e2e"
TARGET = "performance"
BASELINE = "balanced"
STATE_DIR: Path | None = None
LOG: Path | None = None
CANCEL: Path | None = None
EXPIRED: Path | None = None
LOCK: Path | None = None
DEADLINE = float("inf")
WATCHDOG_SECONDS = 30.0
MAX_BASELINE_TEMP = 60.0
EMERGENCY_TEMP = 85.0
VERIFICATION_DELAYS = (0.0, 0.4, 0.6, 1.0)
AWCCD_SOCKET = Path("/run/awcc/awccd.sock")


def command(*args: str, timeout: float = 12.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, capture_output=True, text=True, timeout=timeout)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def event(kind: str, **data: object) -> None:
    record = {"time": time.time(), "event": kind, **data}
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    print(line, flush=True)
    assert LOG is not None
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def initialize_state() -> int:
    """Create root-independent, private state and a singleton lock in /tmp."""

    global STATE_DIR, LOG, CANCEL, EXPIRED, LOCK
    lock_path = Path(tempfile.gettempdir()) / "awcc-x17r1-performance-ppd-e2e.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        os.close(fd)
        raise RuntimeError("Unsafe singleton lock.")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise RuntimeError("Another PPD performance diagnostic is running.") from None
    STATE_DIR = Path(tempfile.mkdtemp(prefix="awcc-x17r1-performance-ppd-e2e-"))
    os.chmod(STATE_DIR, 0o700)
    LOG = STATE_DIR / "hardware-test.jsonl"
    CANCEL = STATE_DIR / "watchdog.cancel"
    EXPIRED = STATE_DIR / "watchdog.expired"
    LOCK = STATE_DIR / "mutation.lock"
    return fd


def mutation_lock():
    assert LOCK is not None
    stream = LOCK.open("a", encoding="utf-8")
    fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
    return stream


def profile_path() -> Path:
    for candidate in glob.glob("/sys/class/platform-profile/platform-profile-*/profile"):
        path = Path(candidate)
        try:
            if read(path.with_name("name")) in {"alienware-wmi", "alienware_wmi"}:
                return path
        except OSError:
            continue
    raise RuntimeError("Không tìm thấy alienware-wmi platform profile.")


def temperatures() -> dict[str, float]:
    for name in Path("/sys/class/hwmon").glob("hwmon*/name"):
        try:
            if read(name) != "alienware_wmi":
                continue
            values: dict[str, float] = {}
            for source in name.parent.glob("temp*_input"):
                label = source.with_name(source.name.replace("_input", "_label"))
                values[read(label)] = int(read(source)) / 1000.0
            return values
        except (OSError, ValueError):
            continue
    return {}


def ac_online() -> bool:
    sources = [Path(value) for value in glob.glob("/sys/class/power_supply/AC*/online")]
    return bool(sources) and any(read(source) == "1" for source in sources)


def ppd_get() -> str | None:
    result = command("powerprofilesctl", "get", timeout=5)
    return result.stdout.strip() if result.returncode == 0 else None


def set_ppd(profile: str) -> dict[str, object]:
    result = command("powerprofilesctl", "set", profile)
    return {
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def snapshot() -> dict[str, object]:
    return {
        "daemon": ppd_get(),
        "platform": read(profile_path()),
        "temperatures": temperatures(),
        "awccd_socket": AWCCD_SOCKET.exists(),
    }


def preflight() -> dict[str, object]:
    current = snapshot()
    dmi = {
        "vendor": read(Path("/sys/class/dmi/id/sys_vendor")),
        "model": read(Path("/sys/class/dmi/id/product_name")),
        "bios": read(Path("/sys/class/dmi/id/bios_version")),
    }
    event("preflight", dmi=dmi, snapshot=current, ac_online=ac_online())
    if dmi != {"vendor": "Alienware", "model": "Alienware x17 R1", "bios": "1.27.0"}:
        raise RuntimeError("DMI/BIOS không khớp Alienware x17 R1 BIOS 1.27.0.")
    if not ac_online() or current["daemon"] != BASELINE or current["platform"] != BASELINE:
        raise RuntimeError("AC/PPD/profile Balanced baseline không hợp lệ.")
    if current["awccd_socket"]:
        raise RuntimeError("awccd socket hiện diện; từ chối write Performance.")
    if TARGET not in read(profile_path().with_name("choices")).split():
        raise RuntimeError("Performance không được firmware công bố.")
    temps = current["temperatures"]
    if not temps or max(temps.values()) > MAX_BASELINE_TEMP:
        raise RuntimeError("Nhiệt độ baseline thiếu hoặc > 60 C.")
    return current


def restore_locked() -> bool:
    result: dict[str, object] = {}
    errors: list[str] = []
    try:
        result = set_ppd(BASELINE)
        if result["returncode"] != 0:
            errors.append(f"balanced-ppd: {result!r}")
    except Exception as exc:
        errors.append(f"balanced-ppd: {exc!r}")
    time.sleep(0.2)
    try:
        final = snapshot()
    except Exception as exc:
        final = {}
        errors.append(f"final-snapshot: {exc!r}")
    ok = (
        not errors
        and final.get("daemon") == BASELINE
        and final.get("platform") == BASELINE
        and not final.get("awccd_socket")
    )
    event("restore", ok=ok, result=result, final=final, errors=errors)
    return ok


def restore() -> bool:
    with mutation_lock():
        try:
            return restore_locked()
        finally:
            assert CANCEL is not None
            CANCEL.touch(mode=0o600)


def watchdog() -> None:
    assert CANCEL is not None and EXPIRED is not None
    while time.monotonic() < DEADLINE:
        if CANCEL.exists():
            os._exit(0)
        time.sleep(0.1)
    try:
        with mutation_lock():
            if CANCEL.exists():
                os._exit(0)
            EXPIRED.touch(mode=0o600)
            event("watchdog-fired", restore_ok=restore_locked())
    except Exception as exc:
        event("watchdog-fired", restore_ok=False, error=repr(exc))
    os._exit(0)


def interrupted(signum: int, _frame: object) -> None:
    raise RuntimeError(f"Test interrupted by signal {signum}; restoring baseline.")


def main(argv: list[str] | None = None) -> int:
    global DEADLINE
    args = sys.argv[1:] if argv is None else argv
    if args != [CONFIRM_FLAG]:
        print(f"Refusing: pass {CONFIRM_FLAG} exactly.", file=sys.stderr)
        return 64
    if os.geteuid() == 0:
        raise RuntimeError("Runner phải chạy với desktop user, không qua pkexec.")

    singleton_fd = initialize_state()
    preflight_ok = False
    restored = False
    success = False
    child = -1
    try:
        preflight()
        preflight_ok = True
        DEADLINE = time.monotonic() + WATCHDOG_SECONDS
        child = os.fork()
        if child == 0:
            watchdog()
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGHUP, interrupted)
        with mutation_lock():
            request = set_ppd(TARGET)
        event("performance-request", result=request)
        if request["returncode"] != 0:
            raise RuntimeError(f"powerprofilesctl set failed: {request!r}")

        observations: list[dict[str, object]] = []
        for sample, delay in enumerate(VERIFICATION_DELAYS, start=1):
            if delay:
                time.sleep(delay)
            current = snapshot()
            observations.append(current)
            event("sample", sample=sample, snapshot=current)
            temps = current["temperatures"]
            if current["daemon"] != TARGET or current["platform"] != TARGET:
                raise RuntimeError("PPD/platform profile không giữ Performance.")
            if current["awccd_socket"]:
                raise RuntimeError("awccd socket xuất hiện trong phép thử.")
            if not temps or max(temps.values()) >= EMERGENCY_TEMP:
                raise RuntimeError("Thermal telemetry lost or reached emergency limit.")
            assert EXPIRED is not None
            if EXPIRED.exists() or time.monotonic() >= DEADLINE or not ac_online():
                raise RuntimeError("Watchdog deadline or AC-power guard triggered.")
        success = True
        event("observation", samples=len(observations), target=TARGET)
    except (Exception, KeyboardInterrupt) as exc:
        event("test-error", error=repr(exc))
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        try:
            if preflight_ok:
                restored = restore()
            else:
                event("restore-skipped", reason="preflight failed before any mutation")
        finally:
            if child > 0:
                os.waitpid(child, 0)
            os.close(singleton_fd)
    return 0 if success and restored else 1


if __name__ == "__main__":
    raise SystemExit(main())

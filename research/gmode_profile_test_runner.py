#!/usr/bin/python3
"""One-shot force_gmode profile test with independent rollback watchdog.

Never execute without explicit user approval: this reloads alienware_wmi and
temporarily toggles the firmware Game Shift path through the upstream driver.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import glob
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path


STATE_DIR = Path("/run/awcc-x17r1-gmode-test")
LOG = STATE_DIR / "hardware-test.jsonl"
CANCEL = STATE_DIR / "watchdog.cancel"
EXPIRED = STATE_DIR / "watchdog.expired"
MUTATION_LOCK = STATE_DIR / "mutation.lock"
DEADLINE = float("inf")
SERVICE = "power-profiles-daemon.service"
MODULE = "alienware_wmi"
WATCHDOG_SECONDS = 20
TEMP_LIMIT = 60.0
EMERGENCY_TEMP = 85.0


def initialize_state() -> int:
    """Keep previous evidence; refuse concurrent runs and unsafe lock targets."""
    global STATE_DIR, LOG, CANCEL, EXPIRED, MUTATION_LOCK
    fd = os.open("/run/awcc-x17r1-gmode-test.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_nlink != 1:
        os.close(fd)
        raise RuntimeError("Unsafe singleton lock.")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise RuntimeError("Another G-Mode test is running.") from None
    STATE_DIR = Path(tempfile.mkdtemp(prefix="awcc-x17r1-gmode-test-", dir="/run"))
    LOG = STATE_DIR / "hardware-test.jsonl"
    CANCEL = STATE_DIR / "watchdog.cancel"
    EXPIRED = STATE_DIR / "watchdog.expired"
    MUTATION_LOCK = STATE_DIR / "mutation.lock"
    return fd


@contextmanager
def mutation_lock():
    # Open separately in each process: inherited flock descriptors share locks.
    with MUTATION_LOCK.open("a") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def test_mutation():
    with mutation_lock():
        if EXPIRED.exists() or time.monotonic() >= DEADLINE:
            raise RuntimeError("Watchdog deadline expired; no further test writes allowed.")
        yield


def interrupted(signum: int, _frame: object) -> None:
    raise RuntimeError(f"Test interrupted by signal {signum}; restoring baseline.")


def event(kind: str, **data: object) -> None:
    line = json.dumps({"time": time.time(), "event": kind, **data}, ensure_ascii=False)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def command(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=check,
        capture_output=True,
        text=True,
        timeout=5,
    )


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def service_active() -> bool:
    return command("systemctl", "is-active", "--quiet", SERVICE, check=False).returncode == 0


def set_service(active: bool) -> None:
    command("systemctl", "start" if active else "stop", SERVICE)
    if service_active() != active:
        raise RuntimeError("Không xác minh được trạng thái power-profiles-daemon.")


def module_loaded() -> bool:
    return Path(f"/sys/module/{MODULE}").is_dir()


def module_has_holders() -> bool:
    holders = Path(f"/sys/module/{MODULE}/holders")
    return holders.is_dir() and any(holders.iterdir())


def load_module(force_gmode: bool) -> None:
    args = [
        "modprobe",
        MODULE,
        "force_platform_profile=1",
        "force_hwmon=1",
    ]
    args.append(f"force_gmode={int(force_gmode)}")
    command(*args)


def reload_module(force_gmode: bool) -> None:
    if module_loaded():
        command("modprobe", "-r", MODULE)
    load_module(force_gmode)


def profile_path(timeout: float = 5.0) -> Path:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for candidate in glob.glob("/sys/class/platform-profile/platform-profile-*/profile"):
            path = Path(candidate)
            try:
                if read(path.with_name("name")) == "alienware-wmi":
                    return path
            except OSError:
                pass
        time.sleep(0.1)
    raise RuntimeError("Không tìm thấy alienware-wmi platform profile.")


def awcc_hwmon(timeout: float = 5.0) -> Path:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for name in Path("/sys/class/hwmon").glob("hwmon*/name"):
            try:
                if read(name) == "alienware_wmi":
                    return name.parent
            except OSError:
                pass
        time.sleep(0.1)
    raise RuntimeError("Không tìm thấy alienware_wmi hwmon.")


def temperatures(root: Path) -> dict[str, float]:
    result: dict[str, float] = {}
    for source in root.glob("temp*_input"):
        label_path = source.with_name(source.name.replace("_input", "_label"))
        result[read(label_path)] = int(read(source)) / 1000
    return result


def snapshot() -> dict[str, object]:
    profile = profile_path()
    hwmon = awcc_hwmon()
    rpm = {path.name: int(read(path)) for path in hwmon.glob("fan*_input")}
    boost = {path.name: int(read(path)) for path in hwmon.glob("fan*_boost")}
    return {
        "profile": read(profile),
        "temperatures": temperatures(hwmon),
        "rpm": rpm,
        "boost": boost,
        "service_active": service_active(),
    }


def ac_online() -> bool:
    paths = [Path(item) for item in glob.glob("/sys/class/power_supply/AC*/online")]
    return bool(paths) and any(read(path) == "1" for path in paths)


def restore_locked() -> bool:
    errors: list[str] = []
    try:
        if module_loaded():
            try:
                profile_path().write_text("balanced\n", encoding="utf-8")
                time.sleep(0.3)
            except Exception as exc:
                errors.append(f"balanced-before-reload: {exc!r}")
        reload_module(False)
    except Exception as exc:
        errors.append(f"module-restore: {exc!r}")
    try:
        set_service(True)
    except Exception as exc:
        errors.append(f"service-restore: {exc!r}")
    time.sleep(0.7)
    try:
        final = snapshot()
    except Exception as exc:
        final = {}
        errors.append(f"final-snapshot: {exc!r}")
    ok = not errors and final.get("profile") == "balanced" and service_active()
    event("restore", ok=ok, final=final, errors=errors)
    return ok


def restore() -> bool:
    with mutation_lock():
        ok = restore_locked()
        if ok:
            CANCEL.touch(mode=0o600)
        return ok


def watchdog() -> None:
    while time.monotonic() < DEADLINE:
        if CANCEL.exists():
            os._exit(0)
        time.sleep(0.1)
    try:
        with mutation_lock():
            if CANCEL.exists():
                os._exit(0)
            EXPIRED.touch(mode=0o600)
            ok = restore_locked()
            event("watchdog-fired", restore_ok=ok)
    except Exception as exc:
        event("watchdog-fired", restore_ok=False, error=repr(exc))
    os._exit(0)


def main(argv: list[str] | None = None) -> int:
    global DEADLINE
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-x17r1-force-gmode-test", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_x17r1_force_gmode_test:
        print("Refusing: explicit confirmation flag is required.", file=sys.stderr)
        return 64
    if os.geteuid() != 0:
        raise RuntimeError("Runner phải chạy với EUID 0 qua pkexec.")

    singleton_fd = initialize_state()

    baseline = snapshot()
    dmi = {
        "vendor": read(Path("/sys/class/dmi/id/sys_vendor")),
        "model": read(Path("/sys/class/dmi/id/product_name")),
        "bios": read(Path("/sys/class/dmi/id/bios_version")),
    }
    event(
        "preflight",
        dmi=dmi,
        baseline=baseline,
        ac_online=ac_online(),
        module_holders=module_has_holders(),
        log_path=str(LOG),
    )
    if dmi != {"vendor": "Alienware", "model": "Alienware x17 R1", "bios": "1.27.0"}:
        raise RuntimeError("DMI/BIOS không khớp Alienware x17 R1 BIOS 1.27.0.")
    if not ac_online() or not service_active() or baseline["profile"] != "balanced":
        raise RuntimeError("AC/daemon/profile baseline không hợp lệ.")
    if module_has_holders():
        raise RuntimeError("alienware_wmi đang có module holder.")
    temps = baseline["temperatures"]
    if not temps or max(temps.values()) >= TEMP_LIMIT:
        raise RuntimeError("Nhiệt độ baseline thiếu hoặc >= 60 C.")

    DEADLINE = time.monotonic() + WATCHDOG_SECONDS
    child = os.fork()
    if child == 0:
        watchdog()

    stable = False
    restored = False
    try:
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGHUP, interrupted)
        with test_mutation():
            set_service(False)
        event("power-profiles-daemon", active=False)
        with test_mutation():
            reload_module(True)
        forced_baseline = snapshot()
        event("force-gmode-loaded", snapshot=forced_baseline)
        profile = profile_path()
        with test_mutation():
            profile.write_text("performance\n", encoding="utf-8")
        event("performance-requested", immediate=read(profile))
        observations: list[dict[str, object]] = []
        for sample in range(1, 13):
            time.sleep(0.25)
            current = snapshot()
            observations.append(current)
            event("sample", sample=sample, snapshot=current)
            current_temps = current["temperatures"]
            if service_active():
                raise RuntimeError("power-profiles-daemon tự active lại.")
            if not current_temps:
                raise RuntimeError("Temperature telemetry lost; aborting.")
            if max(current_temps.values()) >= EMERGENCY_TEMP:
                raise RuntimeError("Thermal watchdog reached 85 C.")
            if EXPIRED.exists() or time.monotonic() >= DEADLINE:
                raise RuntimeError("Watchdog deadline reached.")
            if not ac_online():
                raise RuntimeError("AC power lost; aborting.")
        stable = all(item["profile"] == "performance" for item in observations)
        event("test-result", stable=stable)
    except (Exception, KeyboardInterrupt) as exc:
        event("test-error", error=repr(exc))
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        try:
            restored = restore()
        finally:
            os.waitpid(child, 0)
            os.close(singleton_fd)

    return 0 if stable and restored else 1


if __name__ == "__main__":
    raise SystemExit(main())

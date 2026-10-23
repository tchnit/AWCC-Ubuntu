#!/usr/bin/python3
"""One-shot ordinary-profile diagnostic on the verified Alienware x17 R1.

The runner never runs without its explicit command-line guard and root EUID.
It temporarily substitutes *only* the prebuilt logging candidate for
``alienware_wmi``, stops power-profiles-daemon, asks firmware once for Quiet,
and restores the stock driver, Balanced and the daemon through both a normal
path and an independent watchdog.  It is an evidence-gathering experiment,
not fan control.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import glob
import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path


MODULE = "alienware_wmi"
SERVICE = "power-profiles-daemon.service"
TARGET_PROFILE = "quiet"
STATE_DIR = Path("/run/awcc-x17r1-profile-diagnostic")
LOG = STATE_DIR / "hardware-test.jsonl"
CANCEL = STATE_DIR / "watchdog.cancel"
EXPIRED = STATE_DIR / "watchdog.expired"
MUTATION_LOCK = STATE_DIR / "mutation.lock"
CANDIDATE_COPY = STATE_DIR / "alienware-wmi-diagnostic.ko"
CANDIDATE = Path(__file__).resolve().parent / "alienware-module-diagnostic/alienware-wmi.ko"
EXPECTED_MODULE_SHA256 = "05f4055f0a9087588e32f8a7b25f30fae228cd81788f042d1a9a8b236e56f878"
EXPECTED_SRCVERSION = "9CD2136C047452D3F372B09"
WATCHDOG_SECONDS = 30
TEMP_LIMIT = 60.0
EMERGENCY_TEMP = 85.0
SAMPLE_INTERVAL = 0.25
SAMPLE_COUNT = 10
DEADLINE = float("inf")


def command(*args: str, check: bool = True, timeout: float = 8.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, capture_output=True, text=True, timeout=timeout)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def event(kind: str, **data: object) -> None:
    record = {"time": time.time(), "event": kind, **data}
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def initialize_state() -> int:
    """Make a fresh root-owned state area while preserving earlier evidence."""
    global STATE_DIR, LOG, CANCEL, EXPIRED, MUTATION_LOCK, CANDIDATE_COPY
    fd = os.open("/run/awcc-x17r1-profile-diagnostic.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o077:
        os.close(fd)
        raise RuntimeError("Unsafe singleton lock.")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise RuntimeError("Another profile diagnostic is running.") from None
    STATE_DIR = Path(tempfile.mkdtemp(prefix="awcc-x17r1-profile-diagnostic-", dir="/run"))
    LOG = STATE_DIR / "hardware-test.jsonl"
    CANCEL = STATE_DIR / "watchdog.cancel"
    EXPIRED = STATE_DIR / "watchdog.expired"
    MUTATION_LOCK = STATE_DIR / "mutation.lock"
    CANDIDATE_COPY = STATE_DIR / "alienware-wmi-diagnostic.ko"
    return fd


@contextmanager
def mutation_lock():
    with MUTATION_LOCK.open("a", encoding="utf-8") as stream:
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
    values: dict[str, float] = {}
    for source in root.glob("temp*_input"):
        label = source.with_name(source.name.replace("_input", "_label"))
        values[read(label)] = int(read(source)) / 1000
    return values


def snapshot() -> dict[str, object]:
    profile = profile_path()
    hwmon = awcc_hwmon()
    return {
        "profile": read(profile),
        "temperatures": temperatures(hwmon),
        "rpm": {path.name: int(read(path)) for path in hwmon.glob("fan*_input")},
        "service_active": service_active(),
        "module_srcversion": read(Path(f"/sys/module/{MODULE}/srcversion")),
    }


def ac_online() -> bool:
    supplies = [Path(item) for item in glob.glob("/sys/class/power_supply/AC*/online")]
    return bool(supplies) and any(read(item) == "1" for item in supplies)


def stage_candidate() -> str:
    """Copy the audited inode to root-only /run after hashing it exactly once."""
    fd = os.open(CANDIDATE, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise RuntimeError("Diagnostic candidate is not a regular file.")
        with os.fdopen(os.dup(fd), "rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != EXPECTED_MODULE_SHA256:
            raise RuntimeError(f"Diagnostic candidate SHA-256 mismatch: {digest}")
        out = os.open(CANDIDATE_COPY, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            while block := os.read(fd, 1024 * 1024):
                view = memoryview(block)
                while view:
                    view = view[os.write(out, view):]
        finally:
            os.close(out)
    finally:
        os.close(fd)
    with CANDIDATE_COPY.open("rb") as stream:
        copied = hashlib.file_digest(stream, "sha256").hexdigest()
    if copied != EXPECTED_MODULE_SHA256:
        raise RuntimeError("Staged diagnostic candidate SHA-256 mismatch.")
    return copied


def unload_module() -> None:
    if module_loaded():
        command("modprobe", "-r", MODULE)


def load_stock_module() -> None:
    unload_module()
    command("modprobe", MODULE, "force_platform_profile=1", "force_hwmon=1", "force_gmode=0")


def load_diagnostic_module() -> None:
    unload_module()
    command("insmod", str(CANDIDATE_COPY), "force_platform_profile=1", "force_hwmon=1", "force_gmode=0")
    loaded = read(Path(f"/sys/module/{MODULE}/srcversion"))
    if loaded != EXPECTED_SRCVERSION:
        raise RuntimeError(f"Loaded diagnostic srcversion mismatch: {loaded}")


def diagnostic_messages() -> list[str]:
    result = command("dmesg", "--notime", check=False)
    if result.returncode:
        return [f"dmesg-unavailable: {result.stderr.strip() or result.returncode}"]
    expected = "AWCC_DIAG"
    return [line for line in result.stdout.splitlines() if expected in line]


def restore_locked() -> bool:
    """Emergency-safe restoration. It deliberately runs even after the deadline."""
    errors: list[str] = []
    try:
        if module_loaded():
            try:
                profile_path().write_text("balanced\n", encoding="utf-8")
                time.sleep(0.3)
            except Exception as exc:
                errors.append(f"balanced-before-stock-reload: {exc!r}")
        load_stock_module()
    except Exception as exc:
        errors.append(f"stock-module-restore: {exc!r}")
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


def interrupted(signum: int, _frame: object) -> None:
    raise RuntimeError(f"Test interrupted by signal {signum}; restoring baseline.")


def main(argv: list[str] | None = None) -> int:
    global DEADLINE
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-x17r1-ordinary-profile-diagnostic", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_x17r1_ordinary_profile_diagnostic:
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
    event("preflight", dmi=dmi, baseline=baseline, ac_online=ac_online(),
          module_holders=module_has_holders(), target=TARGET_PROFILE,
          candidate=str(CANDIDATE), log_path=str(LOG))
    if dmi != {"vendor": "Alienware", "model": "Alienware x17 R1", "bios": "1.27.0"}:
        raise RuntimeError("DMI/BIOS không khớp Alienware x17 R1 BIOS 1.27.0.")
    if not ac_online() or not service_active() or baseline["profile"] != "balanced":
        raise RuntimeError("AC/daemon/profile baseline không hợp lệ.")
    if module_has_holders() or TARGET_PROFILE not in read(profile_path().with_name("choices")).split():
        raise RuntimeError("Module đang có holder hoặc Quiet không được firmware công bố.")
    temps = baseline["temperatures"]
    if not temps or max(temps.values()) >= TEMP_LIMIT:
        raise RuntimeError("Nhiệt độ baseline thiếu hoặc >= 60 C.")
    staged_sha = stage_candidate()
    event("candidate-staged", sha256=staged_sha, srcversion=EXPECTED_SRCVERSION)

    DEADLINE = time.monotonic() + WATCHDOG_SECONDS
    child = os.fork()
    if child == 0:
        watchdog()
    restored = False
    safety_failure = False
    try:
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGHUP, interrupted)
        with test_mutation():
            set_service(False)
        event("power-profiles-daemon", active=False)
        with test_mutation():
            load_diagnostic_module()
        diagnostic_baseline = snapshot()
        event("diagnostic-loaded", snapshot=diagnostic_baseline)

        request: dict[str, object]
        with test_mutation():
            try:
                profile_path().write_text(f"{TARGET_PROFILE}\n", encoding="utf-8")
                request = {"write": "returned", "errno": None}
            except OSError as exc:
                request = {"write": "oserror", "errno": exc.errno, "error": str(exc)}
        try:
            request["immediate_profile"] = read(profile_path())
        except Exception as exc:
            request["immediate_profile_error"] = repr(exc)
        event("profile-request", requested=TARGET_PROFILE, result=request)

        observations: list[dict[str, object]] = []
        for sample in range(1, SAMPLE_COUNT + 1):
            time.sleep(SAMPLE_INTERVAL)
            current = snapshot()
            observations.append(current)
            event("sample", sample=sample, snapshot=current)
            current_temps = current["temperatures"]
            if service_active():
                raise RuntimeError("power-profiles-daemon tự active lại.")
            if not current_temps or max(current_temps.values()) >= EMERGENCY_TEMP:
                raise RuntimeError("Thermal telemetry lost or reached emergency limit.")
            if EXPIRED.exists() or time.monotonic() >= DEADLINE or not ac_online():
                raise RuntimeError("Watchdog deadline or AC-power guard triggered.")
        messages = diagnostic_messages()
        event("diagnostic-kernel-log", messages=messages)
        event("observation", target_seen=any(item["profile"] == TARGET_PROFILE for item in observations),
              final_profile=observations[-1]["profile"], samples=len(observations))
    except (Exception, KeyboardInterrupt) as exc:
        safety_failure = True
        event("test-error", error=repr(exc))
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        try:
            restored = restore()
        finally:
            os.waitpid(child, 0)
            os.close(singleton_fd)
    return 1 if safety_failure or not restored else 0


if __name__ == "__main__":
    raise SystemExit(main())

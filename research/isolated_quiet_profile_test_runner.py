#!/usr/bin/python3
"""One stock-driver Quiet test after the competing awccd daemon is isolated.

This runner deliberately does *not* load, unload or modify a kernel module. It
shares the Phase 5C state lock, temperature/AC guards and independent watchdog,
stops power-profiles-daemon, writes Quiet once through the stock platform-profile
ABI, observes for 2.5 seconds, then restores Balanced and PPD.
"""
from __future__ import annotations

from pathlib import Path
import os
import signal
import sys
import time

RESEARCH_DIR = Path(__file__).resolve().parent
if str(RESEARCH_DIR) not in sys.path:
    sys.path.insert(0, str(RESEARCH_DIR))

import diagnostic_profile_test_runner as base


CONFIRM_FLAG = "--confirm-x17r1-isolated-quiet-stock-test"
STOCK_SRCVERSION = "28A4134FBF8432C66D7C668"
AWCCD_SOCKET = Path("/run/awcc/awccd.sock")


def awccd_active() -> bool:
    """Read systemd only; never start, stop or otherwise control awccd."""

    return base.command(
        "systemctl", "is-active", "--quiet", "awccd.service", check=False
    ).returncode == 0


def awccd_isolated() -> bool:
    return not AWCCD_SOCKET.exists() and not awccd_active()


def restore_locked() -> bool:
    """Restore the known profile/daemon baseline even after watchdog expiry."""

    errors: list[str] = []
    try:
        base.profile_path().write_text("balanced\n", encoding="utf-8")
        time.sleep(0.3)
    except Exception as exc:
        errors.append(f"balanced-restore: {exc!r}")
    try:
        base.set_service(True)
    except Exception as exc:
        errors.append(f"ppd-restore: {exc!r}")
    time.sleep(0.7)
    try:
        final = base.snapshot()
    except Exception as exc:
        final = {}
        errors.append(f"final-snapshot: {exc!r}")
    ok = (
        not errors
        and final.get("profile") == "balanced"
        and final.get("module_srcversion") == STOCK_SRCVERSION
        and base.service_active()
        and awccd_isolated()
    )
    base.event("restore", ok=ok, final=final, errors=errors)
    return ok


def restore() -> bool:
    with base.mutation_lock():
        ok = restore_locked()
        if ok:
            base.CANCEL.touch(mode=0o600)
        return ok


def watchdog() -> None:
    while time.monotonic() < base.DEADLINE:
        if base.CANCEL.exists():
            os._exit(0)
        time.sleep(0.1)
    try:
        with base.mutation_lock():
            if base.CANCEL.exists():
                os._exit(0)
            base.EXPIRED.touch(mode=0o600)
            base.event("watchdog-fired", restore_ok=restore_locked())
    except Exception as exc:
        base.event("watchdog-fired", restore_ok=False, error=repr(exc))
    os._exit(0)


def interrupted(signum: int, _frame: object) -> None:
    raise RuntimeError(f"Test interrupted by signal {signum}; restoring baseline.")


def preflight() -> dict[str, object]:
    baseline = base.snapshot()
    dmi = {
        "vendor": base.read(Path("/sys/class/dmi/id/sys_vendor")),
        "model": base.read(Path("/sys/class/dmi/id/product_name")),
        "bios": base.read(Path("/sys/class/dmi/id/bios_version")),
    }
    details = {
        "dmi": dmi,
        "baseline": baseline,
        "ac_online": base.ac_online(),
        "module_holders": base.module_has_holders(),
        "awccd_active": awccd_active(),
        "awccd_socket": AWCCD_SOCKET.exists(),
        "target": base.TARGET_PROFILE,
    }
    base.event("preflight", **details)
    if dmi != {"vendor": "Alienware", "model": "Alienware x17 R1", "bios": "1.27.0"}:
        raise RuntimeError("DMI/BIOS không khớp Alienware x17 R1 BIOS 1.27.0.")
    if not base.ac_online() or not base.service_active() or baseline["profile"] != "balanced":
        raise RuntimeError("AC/PPD/profile baseline không hợp lệ.")
    if baseline["module_srcversion"] != STOCK_SRCVERSION or base.module_has_holders():
        raise RuntimeError("Không phải stock alienware_wmi hoặc module có holder.")
    if not awccd_isolated():
        raise RuntimeError("awccd chưa được cô lập hoàn toàn; từ chối write Quiet.")
    if base.TARGET_PROFILE not in base.read(base.profile_path().with_name("choices")).split():
        raise RuntimeError("Quiet không được firmware công bố.")
    temps = baseline["temperatures"]
    if not temps or max(temps.values()) >= base.TEMP_LIMIT:
        raise RuntimeError("Nhiệt độ baseline thiếu hoặc >= 60 C.")
    return baseline


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args != [CONFIRM_FLAG]:
        print(f"Refusing: pass {CONFIRM_FLAG} exactly.", file=sys.stderr)
        return 64
    if os.geteuid() != 0:
        raise RuntimeError("Runner phải chạy với EUID 0 qua pkexec.")

    singleton_fd = base.initialize_state()
    restored = False
    safety_failure = False
    preflight_ok = False
    child = -1
    try:
        preflight()
        preflight_ok = True
        base.DEADLINE = time.monotonic() + base.WATCHDOG_SECONDS
        child = os.fork()
        if child == 0:
            watchdog()
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGHUP, interrupted)
        with base.test_mutation():
            base.set_service(False)
        base.event("power-profiles-daemon", active=False)
        with base.test_mutation():
            try:
                base.profile_path().write_text(f"{base.TARGET_PROFILE}\n", encoding="utf-8")
                request: dict[str, object] = {"write": "returned", "errno": None}
            except OSError as exc:
                request = {"write": "oserror", "errno": exc.errno, "error": str(exc)}
        try:
            request["immediate_profile"] = base.read(base.profile_path())
        except Exception as exc:
            request["immediate_profile_error"] = repr(exc)
        base.event("profile-request", requested=base.TARGET_PROFILE, result=request)

        observations: list[dict[str, object]] = []
        for sample in range(1, base.SAMPLE_COUNT + 1):
            time.sleep(base.SAMPLE_INTERVAL)
            current = base.snapshot()
            observations.append(current)
            base.event("sample", sample=sample, snapshot=current)
            temps = current["temperatures"]
            if base.service_active() or not awccd_isolated():
                raise RuntimeError("Một controller cạnh tranh đã hoạt động lại.")
            if not temps or max(temps.values()) >= base.EMERGENCY_TEMP:
                raise RuntimeError("Thermal telemetry lost or reached emergency limit.")
            if base.EXPIRED.exists() or time.monotonic() >= base.DEADLINE or not base.ac_online():
                raise RuntimeError("Watchdog deadline or AC-power guard triggered.")
        base.event(
            "observation",
            target_seen=any(item["profile"] == base.TARGET_PROFILE for item in observations),
            final_profile=observations[-1]["profile"],
            samples=len(observations),
        )
    except (Exception, KeyboardInterrupt) as exc:
        safety_failure = True
        base.event("test-error", error=repr(exc))
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        try:
            if preflight_ok:
                restored = restore()
            else:
                base.event("restore-skipped", reason="preflight failed before any mutation")
        finally:
            if child > 0:
                os.waitpid(child, 0)
            os.close(singleton_fd)
    return 1 if safety_failure or not restored else 0


if __name__ == "__main__":
    raise SystemExit(main())

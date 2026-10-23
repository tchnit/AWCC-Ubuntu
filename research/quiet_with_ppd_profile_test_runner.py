#!/usr/bin/python3
"""One stock-driver Quiet test while power-profiles-daemon remains active.

This is a narrowly scoped Phase 5G experiment.  It never stops or starts
power-profiles-daemon during the observation: it writes ``quiet`` once through
the stock platform-profile ABI, observes it for 2.5 seconds, and restores the
known ``balanced`` baseline.  It has the same independent 30-second watchdog
and awccd isolation guard as the preceding Phase 5F runner.
"""
from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path


RESEARCH_DIR = Path(__file__).resolve().parent
if str(RESEARCH_DIR) not in sys.path:
    sys.path.insert(0, str(RESEARCH_DIR))

import diagnostic_profile_test_runner as base
import isolated_quiet_profile_test_runner as isolated


CONFIRM_FLAG = "--confirm-x17r1-quiet-with-ppd-test"
STOCK_SRCVERSION = isolated.STOCK_SRCVERSION


def preflight() -> dict[str, object]:
    """Reject before any write unless the two other profile writers are known."""

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
        "awccd_active": isolated.awccd_active(),
        "awccd_socket": isolated.AWCCD_SOCKET.exists(),
        "target": base.TARGET_PROFILE,
    }
    base.event("preflight", **details)
    if dmi != {"vendor": "Alienware", "model": "Alienware x17 R1", "bios": "1.27.0"}:
        raise RuntimeError("DMI/BIOS không khớp Alienware x17 R1 BIOS 1.27.0.")
    if not base.ac_online() or not base.service_active() or baseline["profile"] != "balanced":
        raise RuntimeError("AC/PPD active/profile Balanced baseline không hợp lệ.")
    if baseline["module_srcversion"] != STOCK_SRCVERSION or base.module_has_holders():
        raise RuntimeError("Không phải stock alienware_wmi hoặc module có holder.")
    if not isolated.awccd_isolated():
        raise RuntimeError("awccd chưa được cô lập hoàn toàn; từ chối write Quiet.")
    if base.TARGET_PROFILE not in base.read(base.profile_path().with_name("choices")).split():
        raise RuntimeError("Quiet không được firmware công bố.")
    temps = baseline["temperatures"]
    if not temps or max(temps.values()) >= base.TEMP_LIMIT:
        raise RuntimeError("Nhiệt độ baseline thiếu hoặc >= 60 C.")
    return baseline


def watchdog() -> None:
    """Restore Balanced if the parent does not complete before the deadline."""

    while time.monotonic() < base.DEADLINE:
        if base.CANCEL.exists():
            os._exit(0)
        time.sleep(0.1)
    try:
        with base.mutation_lock():
            if base.CANCEL.exists():
                os._exit(0)
            base.EXPIRED.touch(mode=0o600)
            base.event("watchdog-fired", restore_ok=isolated.restore_locked())
    except Exception as exc:
        base.event("watchdog-fired", restore_ok=False, error=repr(exc))
    os._exit(0)


def interrupted(signum: int, _frame: object) -> None:
    raise RuntimeError(f"Test interrupted by signal {signum}; restoring baseline.")


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

        # The deliberate difference from Phase 5F: PPD stays active throughout.
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
            if not base.service_active():
                raise RuntimeError("power-profiles-daemon không còn active.")
            if not isolated.awccd_isolated():
                raise RuntimeError("awccd đã hoạt động lại; kết quả không còn cô lập.")
            if not temps or max(temps.values()) >= base.EMERGENCY_TEMP:
                raise RuntimeError("Thermal telemetry lost or reached emergency limit.")
            if base.EXPIRED.exists() or time.monotonic() >= base.DEADLINE or not base.ac_online():
                raise RuntimeError("Watchdog deadline or AC-power guard triggered.")
        base.event(
            "observation",
            target_seen=any(item["profile"] == base.TARGET_PROFILE for item in observations),
            final_profile=observations[-1]["profile"],
            samples=len(observations),
            ppd_active_all_samples=True,
        )
    except (Exception, KeyboardInterrupt) as exc:
        safety_failure = True
        base.event("test-error", error=repr(exc))
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        try:
            if preflight_ok:
                restored = isolated.restore()
            else:
                base.event("restore-skipped", reason="preflight failed before any mutation")
        finally:
            if child > 0:
                os.waitpid(child, 0)
            os.close(singleton_fd)
    return 1 if safety_failure or not restored else 0


if __name__ == "__main__":
    raise SystemExit(main())

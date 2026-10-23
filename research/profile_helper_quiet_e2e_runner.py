#!/usr/bin/python3
"""One end-to-end Quiet check through the installed privileged helper.

The runner is deliberately narrower than a fan experiment: it calls the
installed helper once for Quiet, checks its own 2.75-second read-back result,
then calls that same helper to restore Balanced.  PPD stays active throughout.
An independent watchdog makes the restore request if the parent stops.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import stat
import sys
import time


RESEARCH_DIR = Path(__file__).resolve().parent
if str(RESEARCH_DIR) not in sys.path:
    sys.path.insert(0, str(RESEARCH_DIR))

import diagnostic_profile_test_runner as base
import isolated_quiet_profile_test_runner as isolated


CONFIRM_FLAG = "--confirm-x17r1-profile-helper-quiet-e2e"
HELPER = Path("/usr/libexec/awcc-profile-helper")
STOCK_SRCVERSION = isolated.STOCK_SRCVERSION
# This narrowly scoped UI-path check may start at exactly 60 C, still leaving
# 25 C of margin to the emergency guard.  Temperatures above 60 C are refused.
MAX_BASELINE_TEMP = 60.0


def helper_metadata_is_safe() -> bool:
    try:
        metadata = HELPER.stat()
    except OSError:
        return False
    return (
        HELPER.is_file()
        and metadata.st_uid == 0
        and bool(metadata.st_mode & stat.S_IXUSR)
        and not metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    )


def request(profile: str) -> dict[str, object]:
    """Invoke the installed helper directly as root and preserve its evidence."""

    completed = base.command(str(HELPER), "set-profile", profile, check=False, timeout=12)
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError):
        payload = {"raw_stdout": completed.stdout.strip()}
    return {
        "returncode": completed.returncode,
        "payload": payload,
        "stderr": completed.stderr.strip(),
    }


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
        "helper_safe": helper_metadata_is_safe(),
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
    if not helper_metadata_is_safe():
        raise RuntimeError("Installed profile helper không an toàn hoặc không tồn tại.")
    if not isolated.awccd_isolated():
        raise RuntimeError("awccd chưa được cô lập hoàn toàn; từ chối write Quiet.")
    if base.TARGET_PROFILE not in base.read(base.profile_path().with_name("choices")).split():
        raise RuntimeError("Quiet không được firmware công bố.")
    temps = baseline["temperatures"]
    if not temps or max(temps.values()) > MAX_BASELINE_TEMP:
        raise RuntimeError("Nhiệt độ baseline thiếu hoặc > 60 C.")
    return baseline


def restore_locked() -> bool:
    """Use the same helper to restore Balanced, including after watchdog expiry."""

    errors: list[str] = []
    result: dict[str, object] = {}
    try:
        result = request("balanced")
        payload = result.get("payload")
        if result["returncode"] != 0 or not isinstance(payload, dict) or not payload.get("ok"):
            errors.append(f"balanced-helper: {result!r}")
    except Exception as exc:
        errors.append(f"balanced-helper: {exc!r}")
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
        and isolated.awccd_isolated()
    )
    base.event("restore", ok=ok, helper_result=result, final=final, errors=errors)
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


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args != [CONFIRM_FLAG]:
        print(f"Refusing: pass {CONFIRM_FLAG} exactly.", file=sys.stderr)
        return 64
    if os.geteuid() != 0:
        raise RuntimeError("Runner phải chạy với EUID 0 qua pkexec.")

    singleton_fd = base.initialize_state()
    preflight_ok = False
    restored = False
    safety_failure = False
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
            quiet_result = request(base.TARGET_PROFILE)
        base.event("profile-request", requested=base.TARGET_PROFILE, result=quiet_result)
        payload = quiet_result.get("payload")
        if (
            quiet_result["returncode"] != 0
            or not isinstance(payload, dict)
            or not payload.get("ok")
            or payload.get("final") != base.TARGET_PROFILE
        ):
            raise RuntimeError(f"Quiet helper verification failed: {quiet_result!r}")
        observed = base.snapshot()
        base.event("observation", snapshot=observed)
        if observed["profile"] != base.TARGET_PROFILE:
            raise RuntimeError("Read-only snapshot sau helper không còn là Quiet.")
        if not base.service_active() or not isolated.awccd_isolated():
            raise RuntimeError("PPD/awccd state changed during helper verification.")
        if base.EXPIRED.exists() or time.monotonic() >= base.DEADLINE or not base.ac_online():
            raise RuntimeError("Watchdog deadline or AC-power guard triggered.")
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

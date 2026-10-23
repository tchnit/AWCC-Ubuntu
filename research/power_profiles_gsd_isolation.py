#!/usr/bin/python3
"""Isolate GNOME's power plugin during one reversible power-saver test."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from power_profiles_mode_test import command, profile_path, snapshot


LOG = Path(__file__).parent / "results/hardware-test-ppd-gsd-isolation-2026-10-09.jsonl"
SERVICE = "org.gnome.SettingsDaemon.Power.service"
CONTROL_UNIT = "org.gnome.SettingsDaemon.Power.target"


def event(kind: str, **data: object) -> None:
    line = json.dumps({"time": time.time(), "event": kind, **data}, ensure_ascii=False)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def user_systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", "--user", *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=10,
    )


def wait_for_service_state(expected: str, timeout: float = 7.0) -> str:
    deadline = time.monotonic() + timeout
    state = "unknown"
    while time.monotonic() < deadline:
        state = user_systemctl("is-active", SERVICE, check=False).stdout.strip()
        if state == expected:
            return state
        time.sleep(0.1)
    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-temporary-gsd-power-stop", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_temporary_gsd_power_stop:
        print("Refusing: explicit confirmation flag is required.", file=sys.stderr)
        return 64

    LOG.unlink(missing_ok=True)
    path = profile_path()
    baseline = snapshot(path)
    active_result = user_systemctl("is-active", SERVICE, check=False)
    was_active = active_result.stdout.strip() == "active"
    event(
        "preflight",
        snapshot=baseline,
        service=SERVICE,
        control_unit=CONTROL_UNIT,
        unit_active=was_active,
    )
    if baseline != {"daemon": "balanced", "platform": "balanced"}:
        event("refused", reason="Baseline không phải balanced ở cả hai lớp.")
        return 1
    if not was_active:
        event("refused", reason="gsd-power không active; phép cô lập không có ý nghĩa.")
        return 1

    test_stable = False
    restore_ok = False
    try:
        stopped = user_systemctl("stop", CONTROL_UNIT)
        state_after_stop = wait_for_service_state("inactive")
        event(
            "gsd-power-stopped",
            state=state_after_stop,
            stdout=stopped.stdout.strip(),
            stderr=stopped.stderr.strip(),
        )
        if state_after_stop != "inactive":
            raise RuntimeError(
                f"gsd-power không đạt trạng thái inactive: {state_after_stop!r}."
            )

        command("powerprofilesctl", "set", "power-saver")
        event("power-saver-requested")
        observations: list[dict[str, str]] = []
        for sample in range(1, 9):
            time.sleep(0.25)
            current = snapshot(path)
            observations.append(current)
            event("sample", sample=sample, snapshot=current)
        test_stable = all(
            item == {"daemon": "power-saver", "platform": "low-power"}
            for item in observations
        )
        event("isolation-result", stable=test_stable)
    except Exception as exc:
        event("test-error", error=repr(exc))
    finally:
        errors: list[str] = []
        try:
            command("powerprofilesctl", "set", "balanced")
            time.sleep(0.5)
        except Exception as exc:
            errors.append(f"restore profile: {exc!r}")
        try:
            user_systemctl("start", CONTROL_UNIT)
            wait_for_service_state("active")
        except Exception as exc:
            errors.append(f"restart gsd-power: {exc!r}")
        time.sleep(0.5)
        try:
            restored = snapshot(path)
            service_restored = user_systemctl(
                "is-active", SERVICE, check=False
            ).stdout.strip()
        except Exception as exc:
            restored = {}
            service_restored = "unknown"
            errors.append(f"final read-back: {exc!r}")
        restore_ok = (
            restored == {"daemon": "balanced", "platform": "balanced"}
            and service_restored == "active"
        )
        event(
            "restore",
            ok=restore_ok,
            snapshot=restored,
            unit_state=service_restored,
            errors=errors,
        )

    return 0 if test_stable and restore_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

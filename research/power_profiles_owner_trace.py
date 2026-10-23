#!/usr/bin/python3
"""Trace D-Bus callers while a safe power-saver request rolls back."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from power_profiles_mode_test import command, profile_path, snapshot


LOG = Path(__file__).parent / "results/hardware-test-ppd-owner-trace-2026-10-09.jsonl"


def event(kind: str, **data: object) -> None:
    line = json.dumps({"time": time.time(), "event": kind, **data}, ensure_ascii=False)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-ppd-owner-trace", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_ppd_owner_trace:
        print("Refusing: explicit confirmation flag is required.", file=sys.stderr)
        return 64

    LOG.unlink(missing_ok=True)
    path = profile_path()
    baseline = snapshot(path)
    event("preflight", snapshot=baseline)
    if baseline != {"daemon": "balanced", "platform": "balanced"}:
        return 1

    monitor = subprocess.Popen(
        [
            "dbus-monitor",
            "--system",
            "type='method_call',path='/net/hadess/PowerProfiles',"
            "interface='org.freedesktop.DBus.Properties',member='Set'",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    result = 1
    try:
        time.sleep(0.25)
        command("powerprofilesctl", "set", "power-saver")
        event("power-saver-requested")
        for sample in range(1, 7):
            time.sleep(0.25)
            event("sample", sample=sample, snapshot=snapshot(path))
    except Exception as exc:
        event("test-error", error=repr(exc))
    finally:
        monitor.terminate()
        try:
            trace, _ = monitor.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            monitor.kill()
            trace, _ = monitor.communicate(timeout=3)
        event("dbus-trace", output=trace)

        errors: list[str] = []
        try:
            command("powerprofilesctl", "set", "balanced")
            time.sleep(0.75)
            restored = snapshot(path)
        except Exception as exc:
            errors.append(repr(exc))
            restored = {}
        ok = restored == {"daemon": "balanced", "platform": "balanced"}
        event("restore", ok=ok, snapshot=restored, errors=errors)
        result = 0 if ok else 1

    return result


if __name__ == "__main__":
    raise SystemExit(main())

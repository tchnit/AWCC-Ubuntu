#!/usr/bin/python3
"""Short, reversible performance-profile persistence test."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from power_profiles_mode_test import command, profile_path, snapshot


LOG = Path(__file__).parent / "results/hardware-test-ppd-performance-2026-10-09.jsonl"


def event(kind: str, **data: object) -> None:
    line = json.dumps({"time": time.time(), "event": kind, **data}, ensure_ascii=False)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def temperatures() -> dict[str, float]:
    for name in Path("/sys/class/hwmon").glob("hwmon*/name"):
        if name.read_text(encoding="utf-8").strip() != "alienware_wmi":
            continue
        root = name.parent
        result: dict[str, float] = {}
        for source in root.glob("temp*_input"):
            label_path = source.with_name(source.name.replace("_input", "_label"))
            label = label_path.read_text(encoding="utf-8").strip()
            result[label] = int(source.read_text(encoding="utf-8").strip()) / 1000
        return result
    return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-temporary-performance-test", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_temporary_performance_test:
        print("Refusing: explicit confirmation flag is required.", file=sys.stderr)
        return 64

    LOG.unlink(missing_ok=True)
    path = profile_path()
    baseline = snapshot(path)
    baseline_temps = temperatures()
    event("preflight", snapshot=baseline, temperatures=baseline_temps)
    if baseline != {"daemon": "balanced", "platform": "balanced"}:
        event("refused", reason="Baseline không phải balanced ở cả hai lớp.")
        return 1
    if not baseline_temps or max(baseline_temps.values()) >= 75:
        event("refused", reason="Không có telemetry hoặc nhiệt độ >= 75 C.")
        return 1

    stable = False
    restore_ok = False
    try:
        command("powerprofilesctl", "set", "performance")
        event("performance-requested")
        observations: list[dict[str, str]] = []
        for sample in range(1, 9):
            time.sleep(0.25)
            current = snapshot(path)
            current_temps = temperatures()
            observations.append(current)
            event(
                "sample",
                sample=sample,
                snapshot=current,
                temperatures=current_temps,
            )
            if current_temps and max(current_temps.values()) >= 85:
                raise RuntimeError("Temperature watchdog reached 85 C.")
        stable = all(
            item == {"daemon": "performance", "platform": "performance"}
            for item in observations
        )
        event("test-result", stable=stable)
    except Exception as exc:
        event("test-error", error=repr(exc))
    finally:
        errors: list[str] = []
        try:
            command("powerprofilesctl", "set", "balanced")
            time.sleep(0.75)
            restored = snapshot(path)
        except Exception as exc:
            restored = {}
            errors.append(repr(exc))
        restore_ok = restored == {"daemon": "balanced", "platform": "balanced"}
        event("restore", ok=restore_ok, snapshot=restored, errors=errors)

    return 0 if stable and restore_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

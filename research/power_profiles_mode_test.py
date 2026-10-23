#!/usr/bin/python3
"""One-shot power-profiles-daemon routing test with balanced rollback."""

from __future__ import annotations

import argparse
import glob
import json
import subprocess
import sys
import time
from pathlib import Path


LOG = Path(__file__).parent / "results/hardware-test-ppd-mode-routing-2026-10-09.jsonl"


def event(kind: str, **data: object) -> None:
    record = {"time": time.time(), "event": kind, **data}
    line = json.dumps(record, ensure_ascii=False)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def command(*args: str) -> str:
    completed = subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return completed.stdout.strip()


def profile_path() -> Path:
    candidates = glob.glob("/sys/class/platform-profile/platform-profile-*/profile")
    for candidate in candidates:
        path = Path(candidate)
        name = path.with_name("name").read_text(encoding="utf-8").strip()
        if name in {"alienware-wmi", "alienware_wmi"}:
            return path
    raise RuntimeError("Không tìm thấy alienware-wmi platform profile.")


def snapshot(path: Path) -> dict[str, str]:
    return {
        "daemon": command("powerprofilesctl", "get"),
        "platform": path.read_text(encoding="utf-8").strip(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--confirm-ppd-power-saver-balanced-test",
        action="store_true",
    )
    args = parser.parse_args(argv)
    if not args.confirm_ppd_power_saver_balanced_test:
        print("Refusing: explicit confirmation flag is required.", file=sys.stderr)
        return 64

    LOG.unlink(missing_ok=True)
    path = profile_path()
    baseline = snapshot(path)
    event("preflight", snapshot=baseline)
    if baseline != {"daemon": "balanced", "platform": "balanced"}:
        event("refused", reason="Baseline không phải balanced ở cả hai lớp.")
        return 1

    success = False
    try:
        command("powerprofilesctl", "set", "power-saver")
        event("power-saver-requested")
        observations: list[dict[str, str]] = []
        for sample in range(1, 9):
            time.sleep(0.25)
            current = snapshot(path)
            observations.append(current)
            event("sample", sample=sample, snapshot=current)
        success = all(
            item == {"daemon": "power-saver", "platform": "low-power"}
            for item in observations
        )
        if not success:
            event("test-error", reason="Daemon/platform read-back không ổn định.")
    except Exception as exc:
        event("test-error", error=repr(exc))
    finally:
        restore_errors: list[str] = []
        try:
            command("powerprofilesctl", "set", "balanced")
        except Exception as exc:
            restore_errors.append(repr(exc))
        time.sleep(0.75)
        try:
            restored = snapshot(path)
        except Exception as exc:
            restored = {}
            restore_errors.append(repr(exc))
        restore_ok = restored == {"daemon": "balanced", "platform": "balanced"}
        event(
            "restore",
            ok=restore_ok,
            snapshot=restored,
            errors=restore_errors,
        )

    return 0 if success and restore_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

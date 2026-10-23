#!/usr/bin/python3
"""Root-only PPD-isolated performance persistence test with watchdog."""

from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path


STATE_DIR = Path("/run/awcc-x17r1-performance-isolation")
CANCEL = STATE_DIR / "watchdog.cancel"
LOG = STATE_DIR / "hardware-test.jsonl"
SERVICE = "power-profiles-daemon.service"


def event(kind: str, **data: object) -> None:
    line = json.dumps({"time": time.time(), "event": kind, **data}, ensure_ascii=False)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def profile_path() -> Path:
    for candidate in glob.glob("/sys/class/platform-profile/platform-profile-*/profile"):
        path = Path(candidate)
        if read(path.with_name("name")) in {"alienware-wmi", "alienware_wmi"}:
            return path
    raise RuntimeError("Không tìm thấy alienware-wmi platform profile.")


def temperatures() -> dict[str, float]:
    for name in Path("/sys/class/hwmon").glob("hwmon*/name"):
        if read(name) != "alienware_wmi":
            continue
        result: dict[str, float] = {}
        for source in name.parent.glob("temp*_input"):
            label = read(source.with_name(source.name.replace("_input", "_label")))
            result[label] = int(read(source)) / 1000
        return result
    return {}


def service_active() -> bool:
    return subprocess.run(
        ["systemctl", "is-active", "--quiet", SERVICE],
        check=False,
        timeout=5,
    ).returncode == 0


def set_service(active: bool) -> None:
    subprocess.run(
        ["systemctl", "start" if active else "stop", SERVICE],
        check=True,
        timeout=10,
    )
    if service_active() != active:
        raise RuntimeError("Không xác minh được trạng thái power-profiles-daemon.")


def ac_online() -> bool:
    paths = [Path(value) for value in glob.glob("/sys/class/power_supply/AC*/online")]
    return bool(paths) and any(read(path) == "1" for path in paths)


def restore(path: Path) -> bool:
    errors: list[str] = []
    try:
        path.write_text("balanced\n", encoding="utf-8")
    except Exception as exc:
        errors.append(f"profile: {exc!r}")
    try:
        set_service(True)
    except Exception as exc:
        errors.append(f"service: {exc!r}")
    time.sleep(0.5)
    final_profile = read(path)
    ok = not errors and final_profile == "balanced" and service_active()
    event("restore", ok=ok, profile=final_profile, service_active=service_active(), errors=errors)
    return ok


def watchdog(path: Path) -> None:
    time.sleep(15)
    if CANCEL.exists():
        os._exit(0)
    try:
        ok = restore(path)
        event("watchdog-fired", restore_ok=ok)
    except Exception as exc:
        event("watchdog-fired", restore_ok=False, error=repr(exc))
    os._exit(0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-ppd-isolated-performance-test", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_ppd_isolated_performance_test:
        print("Refusing: explicit confirmation flag is required.", file=sys.stderr)
        return 64
    if os.geteuid() != 0:
        raise RuntimeError("Runner yêu cầu EUID 0 qua pkexec.")

    STATE_DIR.mkdir(mode=0o700, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    LOG.unlink(missing_ok=True)
    CANCEL.unlink(missing_ok=True)
    path = profile_path()
    temps = temperatures()
    preflight = {
        "vendor": read(Path("/sys/class/dmi/id/sys_vendor")),
        "model": read(Path("/sys/class/dmi/id/product_name")),
        "bios": read(Path("/sys/class/dmi/id/bios_version")),
        "profile": read(path),
        "service_active": service_active(),
        "ac_online": ac_online(),
        "temperatures": temps,
    }
    event("preflight", **preflight)
    if preflight["vendor"] != "Alienware" or preflight["model"] != "Alienware x17 R1":
        raise RuntimeError("DMI không khớp máy thử nghiệm.")
    if not preflight["service_active"] or not preflight["ac_online"]:
        raise RuntimeError("Daemon/AC baseline không hợp lệ.")
    if preflight["profile"] != "balanced":
        raise RuntimeError("Profile baseline không phải balanced.")
    if not temps or max(temps.values()) >= 75:
        raise RuntimeError("Telemetry thiếu hoặc baseline >= 75 C.")

    child = os.fork()
    if child == 0:
        watchdog(path)

    restored = False
    stable = False
    try:
        set_service(False)
        event("power-profiles-daemon", active=False)
        path.write_text("performance\n", encoding="utf-8")
        event("performance-requested", immediate_readback=read(path))
        observations: list[str] = []
        for sample in range(1, 9):
            time.sleep(0.25)
            current = read(path)
            current_temps = temperatures()
            observations.append(current)
            event("sample", sample=sample, profile=current, temperatures=current_temps)
            if service_active():
                raise RuntimeError("Daemon tự active lại trong phép thử.")
            if current_temps and max(current_temps.values()) >= 85:
                raise RuntimeError("Temperature watchdog reached 85 C.")
        stable = all(value == "performance" for value in observations)
        event("test-result", stable=stable, observations=observations)
    except Exception as exc:
        event("test-error", error=repr(exc))
    finally:
        restored = restore(path)
        if restored:
            CANCEL.touch(mode=0o600)
        os.waitpid(child, 0)

    return 0 if stable and restored else 1


if __name__ == "__main__":
    raise SystemExit(main())

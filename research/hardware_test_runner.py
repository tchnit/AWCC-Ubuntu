#!/usr/bin/python3
"""One-shot x17 R1 hardware experiment. Install root-owned before execution."""

from __future__ import annotations

import glob
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path


CANDIDATE = Path("/run/awcc-x17r1/dell-smm-hwmon-x17r1.ko")
CANCEL = Path("/run/awcc-x17r1/watchdog.cancel")
LOG = Path("/run/awcc-x17r1/hardware-test.jsonl")
TEMP_LIMIT = 60.0
TEMP_RISE_LIMIT = 5.0
WATCHDOG_SECONDS = 15


def event(kind: str, **data: object) -> None:
    record = {"time": time.time(), "event": kind, **data}
    line = json.dumps(record, ensure_ascii=False)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def write(path: Path, value: int) -> None:
    path.write_text(f"{value}\n", encoding="utf-8")


def command(*args: str) -> None:
    event("command", argv=args)
    subprocess.run(args, check=True, timeout=10)


def dell_hwmon(timeout: float = 5.0) -> Path:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for name in glob.glob("/sys/class/hwmon/hwmon*/name"):
            path = Path(name)
            try:
                if read(path) == "dell_smm":
                    return path.parent
            except OSError:
                pass
        time.sleep(0.1)
    raise RuntimeError("Không tìm thấy dell_smm hwmon.")


def sample(root: Path) -> dict[str, object]:
    temperatures: dict[str, float] = {}
    fans: dict[str, int] = {}
    for path in sorted(root.glob("temp*_input")):
        temperatures[path.name] = int(read(path)) / 1000.0
    for path in sorted(root.glob("fan*_input")):
        fans[path.name] = int(read(path))
    if not temperatures or len(fans) != 4:
        raise RuntimeError("Telemetry thiếu hoặc stale.")
    return {"temperatures": temperatures, "fans": fans}


def all_max(root: Path) -> None:
    pwms = sorted(root.glob("pwm[1-4]"))
    if len(pwms) != 4:
        raise RuntimeError(f"Cần 4 PWM nodes, tìm thấy {len(pwms)}.")
    for path in pwms:
        write(path, 255)


def restore_auto(root: Path) -> bool:
    try:
        all_max(root)
        write(root / "pwm1_enable", 2)
        event("restore-auto-write", ok=True)
        return True
    except Exception as exc:  # emergency path must keep going
        event("restore-auto-write", ok=False, error=repr(exc))
        return False


def watchdog_child() -> None:
    time.sleep(WATCHDOG_SECONDS)
    if CANCEL.exists():
        os._exit(0)
    try:
        root = dell_hwmon(1.0)
        ok = restore_auto(root)
        event("watchdog-fired", restore_ok=ok)
    except Exception as exc:
        event("watchdog-fired", restore_ok=False, error=repr(exc))
    os._exit(0)


def preflight() -> None:
    if os.geteuid() != 0:
        raise RuntimeError("Runner phải chạy với EUID 0.")
    if read(Path("/sys/class/dmi/id/sys_vendor")) != "Alienware":
        raise RuntimeError("Sai system vendor.")
    if read(Path("/sys/class/dmi/id/product_name")) != "Alienware x17 R1":
        raise RuntimeError("Sai product name.")
    if read(Path("/sys/class/power_supply/ACAD/online")) != "1":
        raise RuntimeError("AC không online.")
    if read(Path("/sys/class/platform-profile/platform-profile-0/profile")) != "balanced":
        raise RuntimeError("Profile không phải balanced.")
    if not CANDIDATE.is_file() or CANDIDATE.stat().st_uid != 0:
        raise RuntimeError("Candidate không tồn tại hoặc không root-owned.")
    root = dell_hwmon()
    baseline = sample(root)
    hottest = max(baseline["temperatures"].values())
    enables = [read(path) for path in sorted(root.glob("pwm[1-4]_enable"))]
    if enables != ["2", "2", "2", "2"]:
        raise RuntimeError(f"Baseline không phải BIOS auto: {enables}")
    if hottest > TEMP_LIMIT:
        raise RuntimeError(f"Nhiệt độ baseline quá cao: {hottest} °C")
    event("preflight-pass", baseline=baseline)


def verify_candidate_interface(root: Path) -> None:
    enables = sorted(root.glob("pwm*_enable"))
    if [path.name for path in enables] != ["pwm1_enable"]:
        raise RuntimeError(f"Global interface không đúng: {[p.name for p in enables]}")
    mode = stat.S_IMODE(enables[0].stat().st_mode)
    if mode != 0o200:
        raise RuntimeError(f"pwm1_enable không write-only: mode={mode:o}")
    if len(list(root.glob("pwm[1-4]"))) != 4:
        raise RuntimeError("Candidate không expose đủ 4 PWM nodes.")
    event("candidate-interface-pass", pwm_enable_mode=f"{mode:o}")


def main() -> int:
    preflight()
    candidate_loaded = False
    auto_restored = False
    watchdog_pid: int | None = None
    if CANCEL.exists():
        CANCEL.unlink()

    try:
        command("modprobe", "-r", "dell_smm_hwmon")
        command("insmod", str(CANDIDATE))
        candidate_loaded = True
        root = dell_hwmon()
        verify_candidate_interface(root)

        all_max(root)
        event("all-max-before-manual", snapshot=sample(root))

        watchdog_pid = os.fork()
        if watchdog_pid == 0:
            watchdog_child()

        write(root / "pwm1_enable", 1)
        event("manual-command-returned")
        all_max(root)
        baseline = sample(root)
        baseline_hot = max(baseline["temperatures"].values())
        event("manual-all-max", snapshot=baseline)

        write(root / "pwm1", 128)
        event("fan1-middle-requested")
        for second in range(1, 9):
            time.sleep(1)
            current = sample(root)
            hottest = max(current["temperatures"].values())
            event("manual-sample", second=second, snapshot=current)
            if hottest > TEMP_LIMIT or hottest - baseline_hot >= TEMP_RISE_LIMIT:
                raise RuntimeError(
                    f"Thermal abort: hottest={hottest}, baseline={baseline_hot}"
                )

        all_max(root)
        auto_restored = restore_auto(root)
        if not auto_restored:
            raise RuntimeError("Không phục hồi được BIOS auto.")
        CANCEL.touch(mode=0o600)
        if watchdog_pid is not None:
            os.waitpid(watchdog_pid, 0)
            watchdog_pid = None

        # The candidate is loaded directly with insmod and is intentionally not
        # installed in modules.dep.  rmmod addresses the loaded module by name;
        # `modprobe -r` can fail with "Module ... not found" in this situation.
        command("rmmod", "dell_smm_hwmon_x17r1")
        candidate_loaded = False
        command("modprobe", "dell_smm_hwmon")
        stock = dell_hwmon()
        enables = [read(path) for path in sorted(stock.glob("pwm[1-4]_enable"))]
        if enables != ["2", "2", "2", "2"]:
            raise RuntimeError(f"Stock module chưa trở về BIOS auto: {enables}")
        event("test-complete", result="success", final=sample(stock), pwm_enable=enables)
        return 0
    except Exception as exc:
        event("test-error", error=repr(exc))
        if candidate_loaded:
            try:
                root = dell_hwmon(1.0)
                auto_restored = restore_auto(root)
            except Exception as restore_exc:
                event("emergency-restore-error", error=repr(restore_exc))
        if auto_restored:
            CANCEL.touch(mode=0o600)
            try:
                command("rmmod", "dell_smm_hwmon_x17r1")
                candidate_loaded = False
                command("modprobe", "dell_smm_hwmon")
            except Exception as module_exc:
                event("module-restore-error", error=repr(module_exc))
        if watchdog_pid is not None:
            try:
                os.waitpid(watchdog_pid, 0)
            except ChildProcessError:
                pass
        return 1


if __name__ == "__main__":
    sys.exit(main())

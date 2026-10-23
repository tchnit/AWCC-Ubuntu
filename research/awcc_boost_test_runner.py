#!/usr/bin/python3
"""One-shot x17 R1 immediate custom+boost experiment.

Never run this hardware-writing experiment without explicit user approval.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path


STATE_DIR = Path("/run/awcc-x17r1-custom-boost-handshake-test")
CANCEL = STATE_DIR / "watchdog.cancel"
LOG = STATE_DIR / "hardware-test.jsonl"
TEST_CHANNEL = 1
TEST_BOOST = 224
TEST_SECONDS = 8
HANDSHAKE_SAMPLES = 12
HANDSHAKE_INTERVAL = 0.25
WATCHDOG_SECONDS = 25
TEMP_LIMIT = 60.0
TEMP_RISE_LIMIT = 5.0
MIN_RPM_CHANGE = 100


def event(kind: str, **data: object) -> None:
    record = {"time": time.time(), "event": kind, **data}
    line = json.dumps(record, ensure_ascii=False)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def read_int(path: Path) -> int:
    return int(read(path))


def write_int(path: Path, value: int) -> None:
    path.write_text(f"{value}\n", encoding="utf-8")


def service_active() -> bool:
    return (
        subprocess.run(
            ["systemctl", "is-active", "--quiet", "power-profiles-daemon.service"],
            check=False,
            timeout=5,
        ).returncode
        == 0
    )


def set_service(active: bool) -> None:
    action = "start" if active else "stop"
    subprocess.run(
        ["systemctl", action, "power-profiles-daemon.service"],
        check=True,
        timeout=10,
    )
    if service_active() != active:
        raise RuntimeError(f"power-profiles-daemon không chuyển sang {action}.")
    event("power-profiles-daemon", active=active)


def named_hwmon(expected: str, timeout: float = 3.0) -> Path:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for name in glob.glob("/sys/class/hwmon/hwmon*/name"):
            path = Path(name)
            try:
                if read(path) == expected:
                    return path.parent
            except OSError:
                pass
        time.sleep(0.1)
    raise RuntimeError(f"Không tìm thấy hwmon provider {expected!r}.")


def platform_profile() -> Path:
    for name in glob.glob("/sys/class/platform-profile/platform-profile-*/name"):
        path = Path(name)
        if read(path) in {"alienware-wmi", "alienware_wmi"}:
            return path.parent
    raise RuntimeError("Không tìm thấy alienware-wmi platform profile.")


def ac_online() -> bool:
    candidates = glob.glob("/sys/class/power_supply/AC*/online")
    return bool(candidates) and any(read(Path(path)) == "1" for path in candidates)


def ensure_state_dir() -> None:
    try:
        STATE_DIR.mkdir(mode=0o700)
    except FileExistsError:
        pass
    metadata = STATE_DIR.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0:
        raise RuntimeError("State directory không phải root-owned directory.")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise RuntimeError("State directory có quyền quá rộng.")
    LOG.unlink(missing_ok=True)
    CANCEL.unlink(missing_ok=True)


def snapshot(root: Path) -> dict[str, object]:
    temperatures = {
        path.name: read_int(path) / 1000.0
        for path in sorted(root.glob("temp*_input"))
    }
    rpm = {
        path.name: read_int(path)
        for path in sorted(root.glob("fan[1-4]_input"))
    }
    boosts = {
        path.name: read_int(path)
        for path in sorted(root.glob("fan[1-4]_boost"))
    }
    maximums = {
        path.name: read_int(path)
        for path in sorted(root.glob("fan[1-4]_max"))
    }
    if len(temperatures) < 2 or len(rpm) != 4 or len(boosts) != 4:
        raise RuntimeError("AWCC telemetry/boost interface không đầy đủ.")
    if any(value < 0 or value > 255 for value in boosts.values()):
        raise RuntimeError(f"Boost ngoài range: {boosts}")
    if any(value < 0 or value > 100 for value in temperatures.values()):
        raise RuntimeError(f"Nhiệt độ không hợp lệ: {temperatures}")
    return {
        "temperatures": temperatures,
        "rpm": rpm,
        "boosts": boosts,
        "maximums": maximums,
    }


def restore(
    root: Path,
    profile_root: Path,
    original: dict[str, int],
    original_profile: str,
    restart_ppd: bool,
) -> bool:
    ok = True
    errors: list[str] = []
    for filename, value in original.items():
        try:
            write_int(root / filename, value)
        except Exception as exc:  # emergency path must attempt every channel
            ok = False
            errors.append(f"{filename}: {exc!r}")
    try:
        observed = {name: read_int(root / name) for name in original}
        ok = ok and observed == original
    except Exception as exc:
        observed = {}
        ok = False
        errors.append(repr(exc))
    try:
        (profile_root / "profile").write_text(
            f"{original_profile}\n", encoding="utf-8"
        )
        observed_profile = read(profile_root / "profile")
        ok = ok and observed_profile == original_profile
    except Exception as exc:
        observed_profile = ""
        ok = False
        errors.append(f"profile: {exc!r}")
    if restart_ppd:
        try:
            set_service(True)
        except Exception as exc:
            ok = False
            errors.append(f"power-profiles-daemon: {exc!r}")
    event(
        "restore",
        ok=ok,
        requested=original,
        observed=observed,
        requested_profile=original_profile,
        observed_profile=observed_profile,
        ppd_active=service_active(),
        errors=errors,
    )
    return ok


def watchdog_child(original: dict[str, int], original_profile: str) -> None:
    time.sleep(WATCHDOG_SECONDS)
    if CANCEL.exists():
        os._exit(0)
    try:
        root = named_hwmon("alienware_wmi", 1.0)
        ok = restore(root, platform_profile(), original, original_profile, True)
        event("watchdog-fired", restore_ok=ok)
    except Exception as exc:
        event("watchdog-fired", restore_ok=False, error=repr(exc))
    os._exit(0)


def preflight(root: Path) -> dict[str, object]:
    if os.geteuid() != 0:
        raise RuntimeError("Runner phải chạy với EUID 0.")
    if read(Path("/sys/class/dmi/id/sys_vendor")) != "Alienware":
        raise RuntimeError("Sai system vendor.")
    if read(Path("/sys/class/dmi/id/product_name")) != "Alienware x17 R1":
        raise RuntimeError("Sai product name.")
    if not ac_online():
        raise RuntimeError("AC không online.")
    if not service_active():
        raise RuntimeError("power-profiles-daemon không active ở baseline.")
    profile_root = platform_profile()
    if read(profile_root / "profile") != "balanced":
        raise RuntimeError("Profile không phải balanced.")
    if "custom" not in read(profile_root / "choices").split():
        raise RuntimeError("Firmware không công bố profile custom.")
    baseline = snapshot(root)
    hottest = max(baseline["temperatures"].values())
    if hottest > TEMP_LIMIT:
        raise RuntimeError(f"Nhiệt độ baseline quá cao: {hottest} °C")
    current = baseline["boosts"][f"fan{TEST_CHANNEL}_boost"]
    if current < TEST_BOOST:
        raise RuntimeError(
            f"Test không được tăng boost: current={current}, requested={TEST_BOOST}"
        )
    event("preflight-pass", baseline=baseline)
    return baseline


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument(
        "--confirm-x17r1-custom-boost-handshake-test",
        action="store_true",
        help="Required guard after the user explicitly approves the hardware write.",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not args.confirm_x17r1_custom_boost_handshake_test:
        print("Refusing: explicit confirmation flag is required.", file=sys.stderr)
        return 64

    ensure_state_dir()
    root = named_hwmon("alienware_wmi")
    profile_root = platform_profile()
    baseline = preflight(root)
    original = dict(baseline["boosts"])
    original_profile = read(profile_root / "profile")
    watchdog_pid = os.fork()
    if watchdog_pid == 0:
        watchdog_child(original, original_profile)

    restored = False
    try:
        set_service(False)
        handshake_started = time.monotonic_ns()
        (profile_root / "profile").write_text("custom\n", encoding="utf-8")
        # Firmware clears boosts on entry to custom. Re-assert the already-safe,
        # high baseline on every channel immediately, as the AWCC sequence likely
        # does, instead of waiting for the transient custom state to time out.
        for filename, value in original.items():
            write_int(root / filename, value)
        handshake_ms = (time.monotonic_ns() - handshake_started) / 1_000_000
        observed_handshake = {
            filename: read_int(root / filename) for filename in original
        }
        observed_profile = read(profile_root / "profile")
        event(
            "custom-boost-handshake-requested",
            elapsed_ms=handshake_ms,
            requested=original,
            observed=observed_handshake,
            profile=observed_profile,
        )
        if observed_handshake != original:
            raise RuntimeError("Boost read-back không khớp ngay sau handshake.")
        if observed_profile != "custom":
            raise RuntimeError("Profile custom rollback ngay trong handshake.")

        custom_state: dict[str, object] | None = None
        for sample_number in range(1, HANDSHAKE_SAMPLES + 1):
            time.sleep(HANDSHAKE_INTERVAL)
            observed_profile = read(profile_root / "profile")
            custom_state = snapshot(root)
            event(
                "handshake-hold-sample",
                sample=sample_number,
                profile=observed_profile,
                snapshot=custom_state,
            )
            if service_active():
                raise RuntimeError("power-profiles-daemon tự khởi động lại trong test.")
            if observed_profile != "custom":
                raise RuntimeError("Firmware rollback profile custom sau boost handshake.")
            if custom_state["boosts"] != original:
                raise RuntimeError("Firmware không giữ bộ boost handshake.")

        if custom_state is None:
            raise RuntimeError("Không thu được custom baseline.")
        baseline_hot = max(custom_state["temperatures"].values())
        baseline_rpm = custom_state["rpm"][f"fan{TEST_CHANNEL}_input"]
        target = root / f"fan{TEST_CHANNEL}_boost"
        write_int(target, TEST_BOOST)
        if read_int(target) != TEST_BOOST:
            raise RuntimeError("Boost read-back không khớp ngay sau write.")
        event("boost-requested", channel=TEST_CHANNEL, value=TEST_BOOST)

        rpm_values: list[int] = []
        for second in range(1, TEST_SECONDS + 1):
            time.sleep(1)
            current = snapshot(root)
            hottest = max(current["temperatures"].values())
            rpm_values.append(current["rpm"][f"fan{TEST_CHANNEL}_input"])
            event("sample", second=second, snapshot=current)
            if service_active():
                raise RuntimeError("power-profiles-daemon tự khởi động lại trong boost test.")
            if read(profile_root / "profile") != "custom":
                raise RuntimeError("Firmware rollback profile custom trong boost test.")
            if current["boosts"][f"fan{TEST_CHANNEL}_boost"] != TEST_BOOST:
                raise RuntimeError("Firmware không giữ boost được yêu cầu.")
            if hottest > TEMP_LIMIT or hottest - baseline_hot >= TEMP_RISE_LIMIT:
                raise RuntimeError(
                    f"Thermal abort: hottest={hottest}, baseline={baseline_hot}"
                )

        if max(abs(value - baseline_rpm) for value in rpm_values) < MIN_RPM_CHANGE:
            raise RuntimeError("Boost read-back giữ nhưng RPM không đổi đủ để xác minh.")

        restored = restore(root, profile_root, original, original_profile, True)
        if not restored:
            raise RuntimeError("Không khôi phục được boost ban đầu.")
        CANCEL.touch(mode=0o600)
        os.waitpid(watchdog_pid, 0)
        event("test-complete", result="success", final=snapshot(root))
        return 0
    except Exception as exc:
        event("test-error", error=repr(exc))
        if not restored:
            restored = restore(root, profile_root, original, original_profile, True)
        if restored:
            CANCEL.touch(mode=0o600)
        try:
            os.waitpid(watchdog_pid, 0)
        except ChildProcessError:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())

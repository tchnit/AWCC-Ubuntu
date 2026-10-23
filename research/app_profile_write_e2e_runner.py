#!/usr/bin/python3
"""Installed app profile writes and recovery, with an independent watchdog.

Run as the desktop user using the installed application interpreter. Only
Balanced/Quiet are test targets; original Balanced/Performance is restored.
One deliberate missing software readback follows a REAL Balanced write.
No SMM, PWM, fan boost, services or driver mutations.
"""
from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path
import signal
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import power_profiles_performance_e2e_runner as safety
from gi.repository import GLib
from awcc_linux import __version__
from awcc_linux.backend import HardwareBackend
from awcc_linux.helper_integrity import helper_payload_reason
from awcc_linux.power_profiles import PowerProfilesClient, _read_alienware_platform_profile
from awcc_linux.privileged import ProfileClient


CONFIRM = "--confirm-installed-0.1.1-profile-writes"
ORIGINAL: str | None = None
WATCHDOG_SECONDS = 180.0
RESULTS = Path(__file__).resolve().parent / "results/hardware-test-installed-app-profiles-2026-10-13-run2.jsonl"
LAST_TELEMETRY = None


def temperatures() -> dict[str, float]:
    global LAST_TELEMETRY
    snapshot = HardwareBackend().snapshot()
    LAST_TELEMETRY = snapshot
    return {sensor.label: sensor.celsius for sensor in snapshot.temperatures}


def sample() -> dict:
    result = safety.snapshot()
    result["ac_online"] = safety.ac_online()
    if LAST_TELEMETRY is not None:
        result["fans"] = [dict(channel=fan.channel, rpm=fan.rpm, pwm_enable=fan.pwm_enable) for fan in LAST_TELEMETRY.fans]
    return result


def guard() -> dict:
    state = sample()
    temps = state["temperatures"]
    if state["awccd_socket"] or not state["ac_online"]:
        raise RuntimeError("Controller conflict or AC disconnected")
    if not {"CPU", "GPU"} <= temps.keys() or max(temps.values()) >= 85:
        raise RuntimeError("Telemetry lost or thermal ceiling reached")
    if safety.EXPIRED.exists() or time.monotonic() >= safety.DEADLINE:
        raise RuntimeError("Watchdog deadline reached")
    return state


def restore_original() -> bool:
    assert ORIGINAL in {"performance", "balanced"}
    errors = []
    with safety.mutation_lock():
        try:
            request = safety.set_ppd(ORIGINAL)
            if request["returncode"] != 0:
                errors.append(str(request))
            for index, delay in enumerate(safety.VERIFICATION_DELAYS, 1):
                if delay:
                    time.sleep(delay)
                state = sample()
                safety.event("restore-sample", sample=index, snapshot=state)
                if state["daemon"] != ORIGINAL or state["platform"] != ORIGINAL:
                    errors.append(f"restore sample {index} mismatch")
        except Exception as exc:
            errors.append(repr(exc))
        ok = not errors
        safety.event("restore-original", profile=ORIGINAL, ok=ok, errors=errors)
        if ok:
            safety.CANCEL.touch(mode=0o600)
        return ok


def watchdog() -> None:
    # Forked before creating GIO clients/worker threads. No GTK/DBus Python
    # client is used here: recovery only uses the normal-user PPD command.
    while time.monotonic() < safety.DEADLINE:
        if safety.CANCEL.exists():
            os._exit(0)
        time.sleep(0.1)
    if not safety.CANCEL.exists():
        safety.EXPIRED.touch(mode=0o600)
        safety.event("watchdog-fired", ok=restore_original())
    os._exit(0)


def wait_request(client, profile: str, *, helper: bool = False):
    guard()
    if safety.DEADLINE - time.monotonic() < 100:
        raise RuntimeError("Insufficient watchdog margin for another async request")
    loop = GLib.MainLoop()
    result = []
    def finished(value):
        result.append(value)
        loop.quit()
    # The installed async clients execute real subprocesses and PolicyKit.
    setter = client.set_profile if helper else client.set_platform_profile
    started = setter(profile, finished)
    if not started:
        raise RuntimeError(f"Request not started: {result!r}")
    timeout = GLib.timeout_add_seconds(90, lambda: loop.quit() or False)
    loop.run()
    GLib.source_remove(timeout)
    if not result:
        raise RuntimeError("Installed client callback timed out")
    value = result[0]
    safety.event("installed-client-result", profile=profile, route="helper" if helper else "ppd", result=asdict(value), snapshot=guard())
    return value


def observe(profile: str, daemon: str | tuple[str, ...]) -> None:
    allowed_daemons = (daemon,) if isinstance(daemon, str) else daemon
    for index, delay in enumerate(safety.VERIFICATION_DELAYS, 1):
        if delay:
            time.sleep(delay)
        state = guard()
        safety.event("observation", profile=profile, sample=index, snapshot=state)
        if state["platform"] != profile or state["daemon"] not in allowed_daemons:
            raise RuntimeError("Real readback did not retain expected profile")


def preflight() -> dict:
    dmi = Path("/sys/class/dmi/id")
    if [(dmi / name).read_text().strip() for name in ("sys_vendor", "product_name", "bios_version")] != ["Alienware", "Alienware x17 R1", "1.27.0"]:
        raise RuntimeError("Unexpected DMI/BIOS")
    if __version__ not in {"0.1.1", "0.1.2"} or helper_payload_reason() is not None:
        raise RuntimeError("Installed app/helper must both match the validated revision")
    import awcc_linux
    if "/.local/share/alienware-control-center/venv/" not in awcc_linux.__file__:
        raise RuntimeError("Must use installed app interpreter, not checkout source")
    if Path("/sys/module/alienware_wmi/srcversion").read_text().strip() != "28A4134FBF8432C66D7C668":
        raise RuntimeError("Not the validated stock driver")
    state = sample()
    if state["daemon"] != state["platform"] or state["platform"] not in {"balanced", "performance"}:
        raise RuntimeError("Original PPD/platform baseline is not recoverable")
    if not state["ac_online"] or state["awccd_socket"]:
        raise RuntimeError("AC/controller preflight failed")
    temps = state["temperatures"]
    if not {"CPU", "GPU"} <= temps.keys() or max(temps.values()) > 60:
        raise RuntimeError("Baseline telemetry missing or above 60 C")
    for service in ("awccd.service", "i8kmon.service"):
        status = safety.command("systemctl", "is-active", service)
        if status.stdout.strip() != "inactive":
            raise RuntimeError(f"Competing controller {service}: {status.stdout!r}")
    ppd_status = safety.command("powerprofilesctl", "list")
    safety.event("preflight", app_version=__version__, app_module=awcc_linux.__file__, snapshot=state, ppd_status=ppd_status.stdout.strip())
    # PPD degradation is recorded as its API warning. No new High Performance,
    # Low Power or unverified thermal/fan target is part of this test.
    return state


def main(argv=None) -> int:
    global ORIGINAL
    if (sys.argv[1:] if argv is None else argv) != [CONFIRM]:
        return 64
    if os.geteuid() == 0:
        raise RuntimeError("Run as desktop user; helper alone escalates via PolicyKit")
    safety.WATCHDOG_SECONDS = WATCHDOG_SECONDS
    safety.temperatures = temperatures
    lock = safety.initialize_state()
    safety.LOG = RESULTS
    if RESULTS.exists():
        raise RuntimeError("Preserve previous evidence; choose a fresh result file")
    child = -1
    restored = False
    success = False
    try:
        baseline = preflight()
        ORIGINAL = baseline["daemon"]
        safety.DEADLINE = time.monotonic() + WATCHDOG_SECONDS
        child = os.fork()
        if child == 0:
            watchdog()
        for name in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            signal.signal(name, safety.interrupted)

        def faulty_reader():
            reads = 0
            def missing_readback_once():
                nonlocal reads
                actual = _read_alienware_platform_profile()
                reads += 1
                if reads == 2:
                    safety.event("software-fault-injection", actual_platform=actual, supplied_readback=None, note="Real hardware write; one missing software verification sample")
                    return None
                return actual
            return missing_readback_once

        if ORIGINAL == "performance":
            failure_client = PowerProfilesClient(faulty_reader())
            result = wait_request(failure_client, "balanced")
            if result.ok or result.final_profile != ORIGINAL or "Đã khôi phục" not in result.message:
                raise RuntimeError("Installed PPD recovery did not verify the original profile")
            observe(ORIGINAL, ORIGINAL)
            safety.event("real-write-recovery-verified", original=ORIGINAL)

        ppd = PowerProfilesClient()
        result = wait_request(ppd, "balanced")
        if not result.ok:
            raise RuntimeError(result.message)
        observe("balanced", "balanced")

        helper = ProfileClient()
        # Also establishes cached PolicyKit authorization before Quiet.
        result = wait_request(helper, "balanced", helper=True)
        if not result.ok:
            raise RuntimeError(result.message)
        result = wait_request(helper, "quiet", helper=True)
        if not result.ok:
            raise RuntimeError(result.message)
        observe("quiet", ("balanced", "power-saver"))

        quiet_baseline = safety.ppd_get()
        failure_client = PowerProfilesClient(faulty_reader())
        result = wait_request(failure_client, "balanced")
        if result.ok or result.final_profile != "quiet" or "Đã khôi phục" not in result.message:
            raise RuntimeError("Installed recovery did not restore original Quiet/PPD pair")
        observe("quiet", quiet_baseline)
        safety.event("real-write-quiet-recovery-verified", daemon=quiet_baseline)

        result = wait_request(ppd, "balanced")
        if not result.ok:
            raise RuntimeError(result.message)
        observe("balanced", "balanced")
        success = True
        safety.event("test-observations-complete")
    except (Exception, KeyboardInterrupt) as exc:
        safety.event("test-error", error=repr(exc))
    finally:
        for name in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            signal.signal(name, signal.SIG_IGN)
        if child > 0:
            restored = restore_original()
            os.waitpid(child, 0)
        os.close(lock)
    return 0 if success and restored else 1


if __name__ == "__main__":
    raise SystemExit(main())

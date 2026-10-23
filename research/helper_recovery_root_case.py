#!/usr/bin/python3
"""Real Quiet write with one software readback fault; restore Performance.

Only run by the desktop-user guardian after explicit authorization. This uses
the installed root-owned controller, not a patched driver or raw fan command.
"""
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import subprocess
import time

sys.path.insert(0, "/usr/lib/alienware-control-center")
from awcc_linux.backend import HardwareBackend
from awcc_linux import profile_control as controller

CONFIRM = "--confirm-quiet-helper-readback-recovery"


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args != [CONFIRM] or os.geteuid() != 0:
        return 64
    dmi = Path("/sys/class/dmi/id")
    if [(dmi / name).read_text().strip() for name in ("product_name", "bios_version")] != ["Alienware x17 R1", "1.27.0"]:
        raise RuntimeError("DMI/BIOS mismatch")
    snapshot = HardwareBackend().snapshot()
    temps = {t.label: t.celsius for t in snapshot.temperatures}
    ac = list(Path("/sys/class/power_supply").glob("AC*/online"))
    if snapshot.profile.current != "performance" or snapshot.capabilities.external_awccd_controller:
        raise RuntimeError("Not the expected isolated Performance baseline")
    if not {"CPU", "GPU"} <= temps.keys() or max(temps.values()) > 60 or not any(p.read_text().strip() == "1" for p in ac):
        raise RuntimeError("Thermal/AC preflight failed")
    if Path("/sys/module/alienware_wmi/srcversion").read_text().strip() != "28A4134FBF8432C66D7C668":
        raise RuntimeError("Not stock driver")
    original_reader = controller._read
    reads, faults, commands = 0, [], []
    def daemon_run(args, **kwargs):
        start = time.monotonic()
        trace = dict(args=args, timeout=kwargs.get("timeout"))
        try:
            result = subprocess.run(args, **kwargs)
            trace.update(returncode=result.returncode, stdout=result.stdout.strip(), stderr=result.stderr.strip())
            return result
        except subprocess.TimeoutExpired:
            trace["timed_out"] = True
            raise
        finally:
            trace["elapsed_seconds"] = round(time.monotonic() - start, 3)
            commands.append(trace)
    def read(path):
        nonlocal reads
        actual = original_reader(path)
        if path.name == "profile":
            reads += 1
            if reads == 2:
                faults.append(dict(actual_platform=actual, supplied_readback="software-diagnostic-fault"))
                return "software-diagnostic-fault"
        return actual
    controller._read = read
    try:
        result = controller.ProfileController(daemon_runner=daemon_run).set_profile("quiet")
    finally:
        controller._read = original_reader
    print(json.dumps(dict(controller=controller.__file__, faults=faults, commands=commands, result=asdict(result), persistent=result.persistent, final=result.final), ensure_ascii=False), flush=True)
    return 0 if not result.persistent and result.restored and result.final == "performance" and faults and faults[0]["actual_platform"] == "quiet" else 1


if __name__ == "__main__":
    raise SystemExit(main())

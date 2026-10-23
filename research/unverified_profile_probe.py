#!/usr/bin/python3
"""Narrow root diagnostic for two advertised but unverified thermal profiles.

Invoked by a normal-user independent guardian; never used by the desktop app.
Always restores its verified Balanced starting profile. No fan/SMM API.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

sys.path.insert(0, "/usr/lib/alienware-control-center")
from awcc_linux.backend import HardwareBackend
from awcc_linux.discovery import discover

CONFIRM = "--confirm-x17r1-advertised-profile-probe"


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] != CONFIRM or args[1] not in {"balanced-performance", "custom"} or os.geteuid() != 0:
        return 64
    target = args[1]
    backend = HardwareBackend()
    initial = backend.snapshot()
    if (initial.model, initial.bios_version) != ("Alienware x17 R1", "1.27.0"):
        raise RuntimeError("DMI/BIOS mismatch")
    allowed_baselines = {"balanced", "low-power"} if target == "custom" else {"balanced"}
    if initial.profile.current not in allowed_baselines or target not in initial.profile.choices:
        raise RuntimeError("Must start from a verified baseline with advertised target")
    baseline = initial.profile.current
    root = discover().platform_profile
    if root is None:
        raise RuntimeError("Missing Alienware provider")
    profile = root / "profile"
    ac = list(Path("/sys/class/power_supply").glob("AC*/online"))
    samples = []
    requested = restored = success = False
    error = ""
    def guarded(ceiling):
        state = backend.snapshot()
        temps = {t.label: t.celsius for t in state.temperatures}
        if not {"CPU", "GPU"} <= temps.keys() or max(temps.values()) > ceiling:
            raise RuntimeError(f"Thermal guard: {temps}, ceiling {ceiling}")
        if state.capabilities.external_awccd_controller or not any(p.read_text().strip() == "1" for p in ac):
            raise RuntimeError("AC/controller guard failed")
        if any(f.pwm_enable != 2 for f in state.fans) or len(state.fans) != 4:
            raise RuntimeError("BIOS-auto fan state is not intact")
        return state
    guarded(50 if target == "custom" else 60)
    def interrupted(signum, frame):
        raise RuntimeError(f"Interrupted {signum}; restoring {baseline}")
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, interrupted)
    try:
        requested = True
        profile.write_text(target + "\n")
        for delay in (0, .4, .6, 1, 2, 2, 2, 2):
            if delay:
                time.sleep(delay)
            state = guarded(75)
            ppd = subprocess.run(["powerprofilesctl", "get"], capture_output=True, text=True, check=False, timeout=5)
            record = dict(profile=state.profile.current, daemon=ppd.stdout.strip(), temperatures={t.label:t.celsius for t in state.temperatures}, fans=[dict(channel=f.channel,rpm=f.rpm,pwm_enable=f.pwm_enable) for f in state.fans], boosts=[f.boost for f in state.awcc_fans])
            samples.append(record)
            if state.profile.current != target:
                raise RuntimeError("Profile did not retain target")
        success = True
    except (Exception, KeyboardInterrupt) as exc:
        error = repr(exc)
    finally:
        if requested:
            for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
                signal.signal(sig, signal.SIG_IGN)
            try:
                profile.write_text(baseline + "\n")
                restored = True
                for delay in (0, .75, 2):
                    if delay:
                        time.sleep(delay)
                    state = guarded(75)
                    restored = restored and state.profile.current == baseline
            except Exception as exc:
                error += " Restore: " + repr(exc)
    print(json.dumps(dict(target=target, baseline=baseline, attempted=requested, success=success, restored=restored, samples=samples, error=error),ensure_ascii=False), flush=True)
    return 0 if success and restored else 1


if __name__ == "__main__":
    raise SystemExit(main())

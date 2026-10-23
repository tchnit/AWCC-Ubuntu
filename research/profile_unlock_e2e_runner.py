#!/usr/bin/python3
"""Verify newly unlocked profiles through installed 0.1.2 clients, then restore."""
import os
from pathlib import Path
import signal
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parent))
import app_profile_write_e2e_runner as base
from awcc_linux import __version__
from awcc_linux.power_profiles import PowerProfilesClient
from awcc_linux.privileged import ProfileClient

CONFIRM="--confirm-installed-0.1.2-unlocked-profile-e2e"


def main(argv=None):
    if (sys.argv[1:] if argv is None else argv)!=[CONFIRM] or os.geteuid()==0:
        return 64
    if __version__!="0.1.2":
        raise RuntimeError("Use installed app 0.1.2")
    safety=base.safety
    safety.temperatures=base.temperatures
    fd=safety.initialize_state()
    safety.LOG=Path(__file__).resolve().parent/"results/hardware-test-unlocked-app-e2e-2026-10-13-run4.jsonl"
    if safety.LOG.exists():
        raise RuntimeError("Preserve prior evidence")
    child=-1
    success=restored=False
    try:
        initial=base.preflight()
        base.ORIGINAL=initial["daemon"]
        safety.DEADLINE=time.monotonic()+240
        child=os.fork()
        if child==0:
            base.watchdog()
        for sig in (signal.SIGTERM,signal.SIGHUP,signal.SIGINT):
            signal.signal(sig,safety.interrupted)
        ppd=PowerProfilesClient()
        helper=ProfileClient()
        def request(client,profile,daemon,helper_route=False):
            result=base.wait_request(client,profile,helper=helper_route)
            if not result.ok:
                raise RuntimeError(result.message)
            if helper_route:
                daemon=safety.ppd_get()
            base.observe(profile,daemon)
        # Separate helper authentication from PPD: run it first while the
        # operator is present, before any new standard-mode request.
        safety.event("request-start",route="helper",profile="balanced-performance")
        request(helper,"balanced-performance","balanced",True)
        safety.event("request-start",route="ppd",profile="low-power")
        request(ppd,"low-power","power-saver")
        request(ppd,"balanced","balanced")
        # Exercise the same-value Balanced CPU alias from a Balanced baseline.
        request(helper,"balanced-performance","balanced",True)
        request(ppd,"balanced","balanced")
        request(ppd,"low-power","power-saver")
        for _ in range(15):
            state=base.guard()
            safety.event("custom-cooling",snapshot=state)
            if max(state["temperatures"].values())<=50:
                break
            time.sleep(2)
        else:
            raise RuntimeError("Custom baseline not cool enough")
        request(helper,"custom","power-saver",True)
        # Custom can leave PPD already at power-saver: reapply real Low Power.
        request(ppd,"low-power","power-saver")
        request(ppd,"balanced","balanced")
        safety.event("unlocked-profiles-e2e-passed")
        success=True
    except (Exception,KeyboardInterrupt) as exc:
        safety.event("test-error",error=repr(exc))
    finally:
        for sig in (signal.SIGTERM,signal.SIGHUP,signal.SIGINT):
            signal.signal(sig,signal.SIG_IGN)
        if child>0:
            restored=base.restore_original()
            os.waitpid(child,0)
        os.close(fd)
    return 0 if success and restored else 1


if __name__=="__main__":
    raise SystemExit(main())

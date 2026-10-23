#!/usr/bin/python3
"""Normal-user PPD Low Power and guarded root advertised-profile diagnostics."""
import json
import os
from pathlib import Path
import signal
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app_profile_write_e2e_runner as base

CONFIRM = "--confirm-x17r1-remaining-profile-validation"


def main(argv=None):
    if (sys.argv[1:] if argv is None else argv) != [CONFIRM] or os.geteuid() == 0:
        return 64
    safety = base.safety
    safety.temperatures = base.temperatures
    fd = safety.initialize_state()
    safety.LOG = Path(__file__).resolve().parent / "results/hardware-test-remaining-profiles-2026-10-13-run2.jsonl"
    if safety.LOG.exists():
        raise RuntimeError("Refusing to overwrite previous evidence")
    child = -1
    restored = False
    results = {}
    try:
        baseline = base.preflight()
        base.ORIGINAL = baseline["daemon"]
        safety.DEADLINE = time.monotonic() + 180
        child = os.fork()
        if child == 0:
            base.watchdog()
        for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            signal.signal(sig, safety.interrupted)
        request = safety.set_ppd("power-saver")
        safety.event("low-power-request", result=request)
        try:
            if request["returncode"] != 0:
                raise RuntimeError("PPD request rejected")
            for index, delay in enumerate((0,.4,.6,1,2,2,2,2),1):
                if delay:
                    time.sleep(delay)
                state = base.guard()
                safety.event("low-power-sample", sample=index, snapshot=state)
                if (state["daemon"],state["platform"]) != ("power-saver","low-power"):
                    raise RuntimeError("Low Power did not retain target")
            results["low-power"] = True
        except Exception as exc:
            results["low-power"] = False
            safety.event("low-power-error", error=repr(exc))

        for target in ("balanced-performance", "custom"):
            base.guard()
            if safety.DEADLINE-time.monotonic() < 70:
                raise RuntimeError("Insufficient watchdog margin")
            balanced = safety.set_ppd("balanced")
            if balanced["returncode"] != 0:
                raise RuntimeError("Cannot establish Balanced baseline")
            base.observe("balanced", "balanced")
            temps = base.temperatures()
            if target == "custom" and max(temps.values()) > 50:
                results[target] = False
                safety.event("probe-skipped", target=target, reason="Custom baseline requires <=50 C", temperatures=temps)
                continue
            result = safety.command("pkexec", "/usr/bin/python3", str(Path(__file__).with_name("unverified_profile_probe.py")), "--confirm-x17r1-advertised-profile-probe", target, timeout=60)
            payload = None
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                pass
            results[target] = result.returncode == 0 and isinstance(payload,dict) and payload.get("success") and payload.get("restored")
            safety.event("root-probe-result", target=target, returncode=result.returncode, payload=payload, stderr=result.stderr.strip(), snapshot=base.guard())
        safety.event("validation-summary", results=results)
    except (Exception, KeyboardInterrupt) as exc:
        safety.event("test-error", error=repr(exc))
    finally:
        for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            signal.signal(sig, signal.SIG_IGN)
        if child > 0:
            restored = base.restore_original()
            os.waitpid(child,0)
        os.close(fd)
    return 0 if restored else 1


if __name__ == "__main__":
    raise SystemExit(main())

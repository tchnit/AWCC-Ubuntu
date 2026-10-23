#!/usr/bin/python3
"""Run the separately approved PID/comm attribution variant of the profile test.

The underlying runner supplies the DMI, temperature, AC, daemon, module hash,
watchdog and stock-driver restoration gates. This wrapper only selects the
offline-built attribution artefact; it adds no control path.
"""
from __future__ import annotations

from pathlib import Path
import sys

import diagnostic_profile_test_runner as runner


ARTIFACT = Path(__file__).resolve().parent / "alienware-module-attribution/alienware-wmi.ko"
runner.CANDIDATE = ARTIFACT
# Filled after a clean offline build and reviewed before this runner is used.
runner.EXPECTED_MODULE_SHA256 = "2dd22cca0e6457ad904d569e580a2a63d01fbd719defd42be35b9e413a3d9482"
runner.EXPECTED_SRCVERSION = "4F1D3A34919D6751B4CB2EE"


def attribution_messages() -> list[str]:
    """Only collect this build's unique caller-attribution marker."""
    result = runner.command("dmesg", "--notime", check=False)
    if result.returncode:
        return [f"dmesg-unavailable: {result.stderr.strip() or result.returncode}"]
    return [line for line in result.stdout.splitlines() if "AWCC_ATTRIB" in line]


runner.diagnostic_messages = attribution_messages


if __name__ == "__main__":
    raise SystemExit(runner.main(sys.argv[1:]))

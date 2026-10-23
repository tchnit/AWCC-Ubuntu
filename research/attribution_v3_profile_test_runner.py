#!/usr/bin/python3
"""Run the separately approved v3 profile-caller attribution diagnostic.

The underlying Phase 5C runner supplies every hardware safety gate, watchdog
and restoration action. This wrapper only selects the offline-built v3 logging
artefact and requires a distinct acknowledgement before it can delegate.
"""
from __future__ import annotations

from pathlib import Path
import sys

import diagnostic_profile_test_runner as runner


CONFIRM_FLAG = "--confirm-x17r1-profile-attribution-v3"
ARTIFACT = Path(__file__).resolve().parent / "alienware-module-attribution-v3/alienware-wmi.ko"
runner.CANDIDATE = ARTIFACT
runner.EXPECTED_MODULE_SHA256 = "6682c4411caac9b20eaa678a6ba95375c34d91b0b10efc71cba99c9925cecae7"
runner.EXPECTED_SRCVERSION = "73C7975CFD1F773F9C0C7C0"


def trace_messages() -> list[str]:
    """Only collect the v3 build's unique caller-attribution marker."""
    result = runner.command("dmesg", "--notime", check=False)
    if result.returncode:
        return [f"dmesg-unavailable: {result.stderr.strip() or result.returncode}"]
    return [line for line in result.stdout.splitlines() if "AWCC_TRACE" in line]


runner.diagnostic_messages = trace_messages


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args != [CONFIRM_FLAG]:
        print(f"Refusing: pass {CONFIRM_FLAG} exactly.", file=sys.stderr)
        return 64
    return runner.main(["--confirm-x17r1-ordinary-profile-diagnostic"])


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/python3
"""Capture the single separately approved fan3 retry, with no automatic retry."""
import os
from pathlib import Path
import subprocess
import sys

from custom_boost_validation import CONFIRM as ROOT_CONFIRM

CONFIRM = "--confirm-x17r1-fan3-timed-retry-64-100-64-20s"


def main(argv=None):
    if (sys.argv[1:] if argv is None else argv) != [CONFIRM] or os.geteuid() == 0:
        return 64
    root = Path(__file__).resolve().parent
    result = root / "results/hardware-test-custom-boost-2026-10-15-fan3-retry1.jsonl"
    # Never truncate historical evidence or repeat after an ambiguous outcome.
    with result.open("x", encoding="utf-8") as transcript:
        with subprocess.Popen(
            ["pkexec", "/usr/bin/python3", "-I", "-B",
             str(root / "custom_boost_validation.py"), ROOT_CONFIRM, "--channel", "3"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        ) as child:
            for line in child.stdout:
                transcript.write(line)
                transcript.flush()
                print(line, end="", flush=True)
            return child.wait()


if __name__ == "__main__":
    raise SystemExit(main())

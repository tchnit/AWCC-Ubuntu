#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from awcc_linux.experiment import ExperimentPreflight  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only x17 R1 experiment preflight")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--temperature-limit", type=float, default=60.0)
    args = parser.parse_args()

    report = ExperimentPreflight(
        candidate=PROJECT_DIR / "research/module/dell-smm-hwmon-x17r1.ko",
        temperature_limit_c=args.temperature_limit,
    ).run()
    if args.json:
        print(
            json.dumps(
                {
                    "ready": report.ready,
                    "checks": [
                        {"name": item.name, "passed": item.passed, "detail": item.detail}
                        for item in report.checks
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for item in report.checks:
            print(f"[{'PASS' if item.passed else 'FAIL'}] {item.name}: {item.detail}")
        print("READY (read-only gate only)" if report.ready else "NOT READY")
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/python3
"""Compare the installed root helper with this checkout without invoking it."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from awcc_linux.helper_integrity import helper_payload_reason

reason = helper_payload_reason()
print(reason or "Helper root-owned đã khớp mã nguồn hiện tại.")
raise SystemExit(1 if reason else 0)

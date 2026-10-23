from __future__ import annotations

import argparse
import json
import os
import sys
import signal

from .profile_control import ProfileControlError, ProfileController, SAFE_PROFILES


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="awcc-profile-helper",
        description="Privileged, allow-listed platform-profile writer",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    setter = subparsers.add_parser("set-profile")
    setter.add_argument("profile", choices=sorted(SAFE_PROFILES))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if os.geteuid() != 0:
        print(json.dumps({"ok": False, "error": "Helper phải chạy với EUID 0."}))
        return 77

    def interrupted(_signum, _frame):
        raise ProfileControlError("Yêu cầu bị gián đoạn; đang khôi phục profile cũ.")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)

    try:
        if args.command != "set-profile":
            raise ProfileControlError("Lệnh không được hỗ trợ.")
        result = ProfileController().set_profile(args.profile)
    except ProfileControlError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    payload = {
        "ok": result.persistent,
        "requested": result.requested,
        "previous": result.previous,
        "observed": result.observed,
        "final": result.final,
        "persistent": result.persistent,
        "restored": result.restored,
    }
    if not result.persistent:
        recovery = "Đã khôi phục profile cũ." if result.restored else "Không xác minh được khôi phục profile cũ."
        payload["error"] = f"{result.error} {recovery} Trạng thái cuối: {result.final or 'không đọc được'}."
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if result.persistent else 2


if __name__ == "__main__":
    sys.exit(main())

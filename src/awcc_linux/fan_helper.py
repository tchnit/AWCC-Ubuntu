"""Bounded JSON-line session over authenticated inherited pipes, not a system daemon."""
from __future__ import annotations

import json
import os
import select
import signal
import sys
import time

from .fan_integrity import fan_candidate_reason, fan_deployment_reason
from .fan_policy import FanControlError, PROTOCOL, valid_raw
from .fan_session import FanSession


def parse_command(line: bytes) -> dict:
    if len(line) > 256:
        raise FanControlError("Command quá dài.")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise FanControlError("Duplicate protocol key.")
            result[key] = value
        return result
    try:
        value = json.loads(line.decode("utf-8"), object_pairs_hook=unique)
    except (ValueError, UnicodeError) as exc:
        raise FanControlError("JSON command không hợp lệ.") from exc
    if not isinstance(value, dict):
        raise FanControlError("Command phải là object.")
    op = value.get("op")
    if op in ("start", "heartbeat", "stop") and set(value) == {"op"}:
        return value
    if (op == "set" and set(value) == {"op", "channel", "raw", "seq"}
            and type(value["channel"]) is int and value["channel"] in (1, 2, 3, 4)
            and valid_raw(value["raw"])
            and type(value["seq"]) is int and 1 <= value["seq"] <= 1000):
        return value
    raise FanControlError("Command ngoài allow-list.")


def reply(event, **data):
    print(json.dumps({"protocol": PROTOCOL, "event": event, **data}), flush=True)


def serve(session, input_fd=0):
    # Explicit post-auth handshake: opening/closing a window or cancelling an
    # authentication dialog must never implicitly arm a hardware writer.
    handshake_deadline = time.monotonic() + 10
    readable, _, _ = select.select([input_fd], [], [], 10)
    if not readable:
        raise FanControlError("Chưa nhận xác nhận start sau xác thực.")
    buffer = b""
    while b"\n" not in buffer:
        if time.monotonic() >= handshake_deadline:
            raise FanControlError("Start handshake quá hạn.")
        data = os.read(input_fd, 257)
        if not data:
            return
        buffer += data
        if len(buffer) > 256:
            raise FanControlError("Start handshake quá dài.")
        if b"\n" not in buffer:
            readable, _, _ = select.select([input_fd], [], [], 1)
            if not readable:
                raise FanControlError("Start handshake thiếu newline.")
    line, buffer = buffer.split(b"\n", 1)
    command = parse_command(line)
    if command["op"] == "stop":
        return
    if command["op"] != "start":
        raise FanControlError("Command đầu tiên phải là start.")
    session.start()
    reply("ready", levels=session.levels, remaining=max(0, session.deadline - session.clock()))
    last_seq = 0
    while True:
        session.tick()
        # Bound work per loop: floods cannot suppress thermal/lease checks.
        if b"\n" not in buffer:
            readable, _, _ = select.select([input_fd], [], [], 1)
            if readable:
                data = os.read(input_fd, 1024)
                if not data:
                    return  # EOF is a stop request, not a persistent session.
                buffer += data
        if len(buffer) > 4096 or (b"\n" not in buffer and len(buffer) > 256):
            raise FanControlError("Protocol buffer quá dài.")
        for _ in range(4):
            if b"\n" not in buffer:
                break
            line, buffer = buffer.split(b"\n", 1)
            command = parse_command(line)
            if command["op"] == "stop":
                return
            if command["op"] == "heartbeat":
                session.heartbeat()
            elif command["op"] == "set":
                if command["seq"] <= last_seq:
                    raise FanControlError("Command replay/out-of-order.")
                last_seq = command["seq"]
                session.set_boost(command["channel"], command["raw"])
                reply("applied", seq=last_seq, channel=command["channel"], raw=command["raw"], levels=session.levels)
            else:
                raise FanControlError("Không được restart một phiên đang chạy.")
        reply("status", levels=session.levels, remaining=max(0, session.deadline - session.clock()))


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if args not in (["session"], ["validation-session"]) or os.geteuid() != 0:
        reply("error", message="Cần EUID 0 và đúng lệnh session/validation-session.")
        return 64
    # Validation is an explicit PolicyKit-authenticated candidate run, never a UI fallback.
    reason = fan_deployment_reason() if args == ["session"] else fan_candidate_reason()
    if reason:
        reply("error", message=reason)
        return 77
    os.umask(0o077)
    os.environ["PATH"] = "/usr/sbin:/usr/bin:/sbin:/bin"
    from .fan_hardware import NativeFanPort, acquire_singleton
    fd = None
    port = None
    session = None
    error = None
    restored = False
    def interrupted(signum, _frame):
        raise FanControlError(f"Signal {signum}; restoring.")
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, interrupted)
    try:
        fd = acquire_singleton()
        port = NativeFanPort()
        session = FanSession(port)
        reply("starting", audit=str(port.directory / "audit.jsonl"))
        serve(session)
    except (Exception, KeyboardInterrupt) as exc:
        error = str(exc)
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        if session is not None:
            try:
                restored = session.stop()
            except Exception as exc:
                error = f"{error or ''} Recovery: {exc}"
        if port is not None:
            try:
                restored = port.finish()
            except Exception as exc:
                restored = False
                error = f"{error or ''} Guardian: {exc}"
        if fd is not None:
            os.close(fd)
    mutated = session is not None and session.armed
    reply("stopped", restored=restored, mutated=mutated,
          message=error or ("Đã dừng và khôi phục profile chuẩn." if mutated else "Không thực hiện hardware write."))
    return 0 if (restored or not mutated) and error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Non-root background pipe client; GTK never waits for authentication/hardware."""
from __future__ import annotations

from dataclasses import dataclass
from functools import partial
import json
import queue
import select
import subprocess
import threading
import time

from gi.repository import GLib

from .fan_integrity import FAN_HELPER, fan_deployment_reason
from .fan_policy import ACTIVE_SECONDS, PROTOCOL, valid_raw


@dataclass(frozen=True)
class FanClientState:
    running: bool = False
    ready: bool = False
    pending: bool = False
    levels: tuple[int, ...] = (100, 100, 100, 100)
    remaining: float = 0
    cooldown_until: float = 0
    message: str = "Chưa mở phiên điều khiển boost."


def parse_event(line: bytes) -> dict:
    if len(line) > 8192:
        raise ValueError("Phản hồi fan helper quá dài.")
    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("Duplicate fan helper event key.")
            result[key] = item
        return result
    value = json.loads(line, object_pairs_hook=unique)
    if not isinstance(value, dict) or value.get("protocol") != PROTOCOL:
        raise ValueError("Sai protocol fan helper.")
    if value.get("event") not in {"starting", "ready", "status", "applied", "stopped", "error"}:
        raise ValueError("Sai event fan helper.")
    if value["event"] in {"ready", "status", "applied"}:
        levels = value.get("levels")
        if (not isinstance(levels, dict) or set(levels) != {"1", "2", "3", "4"}
                or any(not valid_raw(v) for v in levels.values())
                or sum(v != 100 for v in levels.values()) > 1):
            raise ValueError("Fan helper trả mức boost không hợp lệ.")
    if value["event"] == "applied" and (
            type(value.get("seq")) is not int or not 1 <= value["seq"] <= 1000
            or type(value.get("channel")) is not int or value["channel"] not in (1, 2, 3, 4)
            or not valid_raw(value.get("raw"))
            or value["levels"][str(value["channel"])] != value["raw"]):
        raise ValueError("ACK fan helper không hợp lệ.")
    return value


class FanClient:
    def __init__(self, changed=None, dispatch=GLib.idle_add):
        self.state = FanClientState()
        self.changed = changed or (lambda: None)
        self.dispatch = dispatch
        self.commands = queue.Queue(maxsize=4)
        self.stop_requested = threading.Event()
        self.closed = False
        self.seq = 0
        self.pending_request = None

    @property
    def unavailable_reason(self):
        return fan_deployment_reason()

    @property
    def available(self):
        return self.unavailable_reason is None

    def _publish(self, **values):
        from dataclasses import replace
        self.state = replace(self.state, **values)
        if not self.closed:
            self.changed()
        return GLib.SOURCE_REMOVE

    def start(self):
        if self.closed or self.state.running or not self.available:
            return False
        self.commands = queue.Queue(maxsize=4)
        self.stop_requested.clear()
        self.seq = 0
        self.pending_request = None
        self._publish(running=True, ready=False, pending=False, levels=(100, 100, 100, 100),
                      cooldown_until=0,
                      message="Đang xác thực và khởi tạo phiên Custom có watchdog…")
        threading.Thread(target=self._worker, name="awcc-fan-session", daemon=True).start()
        return True

    def set_boost(self, channel, raw):
        if (self.closed or not self.state.ready or self.state.pending
                or type(channel) is not int or channel not in (1, 2, 3, 4)
                or not valid_raw(raw)):
            return False
        if time.monotonic() < self.state.cooldown_until:
            self._publish(message="Chờ ít nhất 2 giây giữa các lần đổi boost.")
            return False
        proposed = list(self.state.levels)
        proposed[channel - 1] = raw
        if sum(v != 100 for v in proposed) > 1:
            self._publish(message="Đưa kênh đang khác raw 100 về 100 trước khi đổi quạt khác.")
            return False
        if tuple(proposed) == self.state.levels:
            return False
        self.seq += 1
        try:
            request = {"op": "set", "channel": channel, "raw": raw, "seq": self.seq}
            self.commands.put_nowait(request)
        except queue.Full:
            return False
        self.pending_request = request
        self._publish(pending=True, message=f"Đang ghi AWCC kênh {channel}, raw {raw}…")
        return True

    def stop(self):
        self.stop_requested.set()
        self.pending_request = None
        if self.state.running:
            self._publish(ready=False, pending=False, message="Đang dừng và khôi phục; chưa được coi là hoàn tất.")

    def close(self):
        self.closed = True
        self.stop()  # No synchronous GTK wait and no SIGKILL of the recovery owner.

    def _event(self, event):
        kind = event["event"]
        if kind in {"ready", "status", "applied"}:
            levels = tuple(event["levels"][str(i)] for i in range(1, 5))
            values = {"levels": levels}
            if kind == "ready":
                values.update(ready=not self.stop_requested.is_set(), message="Phiên Custom có thời hạn; raw không phải % RPM.")
            if kind == "applied":
                request = self.pending_request
                expected = list(self.state.levels)
                if request is not None:
                    expected[request["channel"] - 1] = request["raw"]
                if (request is None or event.get("seq") != request["seq"]
                        or event.get("channel") != request["channel"]
                        or event.get("raw") != request["raw"]
                        or levels != tuple(expected)):
                    self.stop()
                    self._publish(ready=False, message="Sai ACK; yêu cầu khôi phục.")
                    return False
                self.pending_request = None
                values.update(pending=False, cooldown_until=time.monotonic() + 2,
                              message="Boost đã được ghi và đọc lại; RPM có quán tính.")
            if "remaining" in event:
                try:
                    seconds = float(event["remaining"])
                    if not 0 <= seconds <= ACTIVE_SECONDS:
                        raise ValueError()
                    values["remaining"] = seconds
                    if seconds == 0:
                        values.update(ready=False, message="Hết thời gian phiên; đang chờ xác minh khôi phục.")
                except (TypeError, ValueError):
                    self.stop()
                    return False
            self._publish(**values)
        elif kind == "error":
            self._publish(ready=False, message=str(event.get("message", "Fan helper từ chối.")))
        elif kind == "stopped":
            restored = event.get("restored") is True
            self._publish(running=False, ready=False, pending=False, remaining=0,
                          message=("Không ghi phần cứng. " if event.get("mutated") is False
                                   else "Đã xác minh khôi phục profile chuẩn/boost 0. " if restored
                                   else "CHƯA xác minh khôi phục; hãy kiểm tra máy. ") + str(event.get("message", "")))
        return GLib.SOURCE_REMOVE

    def _worker(self):
        final_seen = False
        child = None
        try:
            child = subprocess.Popen(
                ["pkexec", str(FAN_HELPER), "session"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, bufsize=0,
            )
            buffer = b""
            next_heartbeat = 0.0
            start = time.monotonic()
            stopping = False
            started = False
            while True:
                if self.stop_requested.is_set() and not stopping:
                    stopping = True
                    child.stdin.write(b'{"op":"stop"}\n')
                    child.stdin.flush()
                    child.stdin.close()
                if started and not stopping:
                    now = time.monotonic()
                    if now >= next_heartbeat:
                        child.stdin.write(b'{"op":"heartbeat"}\n')
                        child.stdin.flush()
                        next_heartbeat = now + 1
                    try:
                        command = self.commands.get_nowait()
                    except queue.Empty:
                        command = None
                    if command:
                        child.stdin.write((json.dumps(command) + "\n").encode())
                        child.stdin.flush()
                readable, _, _ = select.select([child.stdout], [], [], .2)
                if readable:
                    data = child.stdout.read(4096)
                    if not data:
                        break
                    buffer += data
                    if len(buffer) > 32768:
                        raise ValueError("Fan helper output quá dài.")
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        event = parse_event(line)
                        if event["event"] == "starting" and not self.stop_requested.is_set():
                            child.stdin.write(b'{"op":"start"}\n')
                            child.stdin.flush()
                            started = True
                        final_seen = final_seen or event["event"] == "stopped"
                        self.dispatch(self._event, event)
                    if final_seen:
                        break  # Never send a heartbeat after the final recovery ACK.
                if time.monotonic() - start > 180:
                    raise TimeoutError("Fan session quá hạn; kiểm tra khôi phục độc lập.")
            if child.poll() is None:
                child.wait(timeout=15)
            if buffer or not final_seen:
                raise RuntimeError("Helper kết thúc mà không có xác nhận khôi phục.")
        except Exception as exc:
            self.dispatch(partial(self._publish, running=False, ready=False, pending=False,
                                  message=f"Fan session lỗi: {exc}. Không tự giả định đã khôi phục."))
        finally:
            if child is not None:
                for stream in (child.stdin, child.stdout):
                    if stream is not None and not stream.closed:
                        stream.close()  # EOF requests helper recovery; never kill its process.
                if child.poll() is None:
                    threading.Thread(target=child.wait, name="awcc-fan-reap", daemon=True).start()
                else:
                    child.wait()

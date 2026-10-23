"""Pure lease supervisor, with an injected independently supervised hardware port."""
from __future__ import annotations

import time
from typing import Protocol

from .fan_policy import (
    ACTIVE_SECONDS, CHANNELS, HEARTBEAT_SECONDS, FanControlError,
    check_levels, check_snapshot,
)
from .models import SystemSnapshot


class FanPort(Protocol):
    def snapshot(self) -> SystemSnapshot: ...
    def ac(self) -> bool: ...
    def ensure_identity(self) -> None: ...
    def daemon(self) -> str: ...
    def arm_recovery(self, original: str) -> None: ...
    def set_cooling(self) -> None: ...
    def enter_custom(self) -> None: ...
    def set_boost(self, channel: int, raw: int) -> None: ...
    def heartbeat(self) -> None: ...
    def recover(self) -> bool: ...
    def sleep(self, seconds: float) -> None: ...


class FanSession:
    """At most 60 seconds in Custom, one changed channel, no persisted/autostart values.

    Hardware calls may block: this object is NOT the watchdog. The port must arm
    an independent process before its first mutation and fence expired writes.
    """

    def __init__(self, port: FanPort, clock=time.monotonic):
        self.port = port
        self.clock = clock
        self.active = False
        self.armed = False
        self.restored: bool | None = None
        self.levels = dict.fromkeys(CHANNELS, 100)
        self.deadline = 0.0
        self.last_heartbeat = 0.0
        self.last_change = float("-inf")
        self.baseline_hot: float | None = None
        self.baseline_temperatures: dict[str, float] = {}

    def _check(self, *, spinning=True):
        self.port.ensure_identity()
        state = self.port.snapshot()
        check_snapshot(state, self.port.ac(), expected_profile="custom", levels=self.levels,
                       baseline_hot=self.baseline_hot, require_spinning=spinning)
        if any(t.label in self.baseline_temperatures and t.celsius - self.baseline_temperatures[t.label] >= 10
               for t in state.temperatures):
            raise FanControlError("Một cảm biến tăng ≥10 °C; dừng và khôi phục.")
        if self.port.daemon() != "power-saver":
            raise FanControlError("PPD đã đổi; dừng phiên.")
        return state

    def start(self) -> None:
        if self.armed or self.active:
            raise FanControlError("Phiên không được khởi động lại.")
        self.port.ensure_identity()
        state = self.port.snapshot()
        check_snapshot(state, self.port.ac(), starting=True)
        original = self.port.daemon()
        if original not in {"balanced", "performance"} or state.profile.current not in {original, "custom"}:
            raise FanControlError("Cần Balanced/Performance hoặc Custom với PPD Balanced/Performance để khôi phục.")
        if any(f.boost != 0 for f in state.awcc_fans) or "custom" not in state.profile.choices:
            raise FanControlError("Baseline phải có boost 0 trên bốn quạt và có Custom.")
        # Port forks its recovery guardian here, before even the PPD mutation.
        self.port.arm_recovery(original)
        self.armed = True
        try:
            self.port.set_cooling()
            state = self.port.snapshot()
            self.baseline_hot = check_snapshot(state, self.port.ac(), starting=True, expected_profile="low-power")
            self.baseline_temperatures = {t.label: t.celsius for t in state.temperatures}
            self.deadline = self.clock() + ACTIVE_SECONDS
            self.port.enter_custom()
            for channel in CHANNELS:
                self.port.set_boost(channel, 100)
            # Sensor/AC/boost guards remain live throughout fan spin-up.
            for index in range(4):
                self.port.sleep(1)
                self._check(spinning=index == 3)
            if self.clock() >= self.deadline:
                raise FanControlError("Khởi tạo đã dùng hết thời gian phiên.")
            self.active = True
            self.last_heartbeat = self.clock()
            self.port.heartbeat()
        except BaseException:
            self.stop()
            raise

    def heartbeat(self) -> None:
        if not self.active:
            raise FanControlError("Phiên chưa sẵn sàng.")
        if self.clock() >= self.deadline or self.clock() - self.last_heartbeat >= HEARTBEAT_SECONDS:
            raise FanControlError("Heartbeat trễ không được gia hạn phiên đã hết hạn.")
        self.last_heartbeat = self.clock()
        self.port.heartbeat()

    def tick(self) -> SystemSnapshot:
        if not self.active:
            raise FanControlError("Phiên chưa sẵn sàng.")
        try:
            now = self.clock()
            if now >= self.deadline or now - self.last_heartbeat >= HEARTBEAT_SECONDS:
                raise FanControlError("Hết lease hoặc mất heartbeat; đang khôi phục.")
            state = self._check()
            if self.clock() >= self.deadline:
                raise FanControlError("Đọc phần cứng kéo dài vượt lease.")
            return state
        except BaseException:
            self.stop()
            raise

    def set_boost(self, channel: int, raw: int) -> None:
        self.tick()
        if type(channel) is not int or channel not in CHANNELS or type(raw) is not int:
            raise FanControlError("Kênh/raw không hợp lệ.")
        proposed = {**self.levels, channel: raw}
        check_levels(proposed)
        if proposed == self.levels:
            return  # No repeated same-value hardware write.
        if self.clock() - self.last_change < 2:
            raise FanControlError("Chờ ít nhất 2 giây giữa các lần đổi boost.")
        try:
            self.port.set_boost(channel, raw)
            self.levels = proposed
            self.last_change = self.clock()
            self.tick()  # Full read-back + guards, not a write-only success.
        except BaseException:
            self.stop()
            raise

    def stop(self) -> bool:
        self.active = False
        if self.armed and self.restored is not True:
            self.restored = self.port.recover()
        return self.restored is True

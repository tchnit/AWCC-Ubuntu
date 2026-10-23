from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .fan_curves import FanCurve, decide_curve_output


class FanActuator(Protocol):
    """Narrow interface for a future independently privileged actuator."""

    def set_duty(self, duty: int) -> None: ...

    def restore_automatic(self) -> None: ...


@dataclass(frozen=True, slots=True)
class RuntimeStatus:
    armed: bool
    last_duty: int | None
    last_temperature: float | None
    last_heartbeat: float | None
    reason: str


class CurveSupervisor:
    """Fail-closed curve runtime; it owns no sysfs implementation itself."""

    def __init__(self, actuator: FanActuator, heartbeat_timeout: float = 5.0) -> None:
        if heartbeat_timeout <= 0:
            raise ValueError("Heartbeat timeout phải dương.")
        self.actuator = actuator
        self.heartbeat_timeout = heartbeat_timeout
        self._armed = False
        self._last_duty: int | None = None
        self._last_temperature: float | None = None
        self._last_heartbeat: float | None = None
        self._reason = "Chưa arm."

    @property
    def status(self) -> RuntimeStatus:
        return RuntimeStatus(
            self._armed,
            self._last_duty,
            self._last_temperature,
            self._last_heartbeat,
            self._reason,
        )

    def arm(self, stable_manual_control: bool, now: float) -> None:
        if not stable_manual_control:
            raise RuntimeError("Không thể arm khi stable manual control chưa xác minh.")
        self._armed = True
        self._last_heartbeat = now
        self._reason = "Runtime đã arm."

    def tick(
        self,
        curve: FanCurve,
        temperature: float,
        sensor_age_seconds: float,
        now: float,
    ) -> RuntimeStatus:
        if not self._armed:
            raise RuntimeError("Runtime chưa arm.")
        decision = decide_curve_output(
            curve,
            temperature,
            sensor_age_seconds,
            stable_manual_control=True,
            previous_temperature=self._last_temperature,
            previous_duty=self._last_duty,
        )
        if not decision.may_write or decision.requested_duty is None:
            self.disarm("Curve decision bị capability gate từ chối.")
            return self.status
        self.actuator.set_duty(decision.requested_duty)
        self._last_duty = decision.requested_duty
        self._last_temperature = temperature
        self._last_heartbeat = now
        self._reason = decision.reason
        return self.status

    def watchdog(self, now: float) -> RuntimeStatus:
        if (
            self._armed
            and self._last_heartbeat is not None
            and now - self._last_heartbeat > self.heartbeat_timeout
        ):
            self.disarm("Heartbeat quá hạn; đã yêu cầu trả về BIOS automatic.")
        return self.status

    def disarm(self, reason: str = "Người dùng dừng runtime.") -> None:
        if self._armed:
            self.actuator.restore_automatic()
        self._armed = False
        self._last_duty = None
        self._last_temperature = None
        self._reason = reason

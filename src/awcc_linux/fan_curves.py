from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, order=True)
class CurvePoint:
    temperature: float
    duty: int

    def __post_init__(self) -> None:
        if not 0 <= self.duty <= 100:
            raise ValueError("Fan duty phải nằm trong khoảng 0..100.")


@dataclass(frozen=True, slots=True)
class FanCurve:
    points: tuple[CurvePoint, ...]
    hysteresis_c: float = 3.0
    minimum_change: int = 3

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ValueError("Fan curve cần ít nhất hai điểm.")
        temperatures = [point.temperature for point in self.points]
        duties = [point.duty for point in self.points]
        if temperatures != sorted(set(temperatures)):
            raise ValueError("Nhiệt độ phải tăng nghiêm ngặt.")
        if duties != sorted(duties):
            raise ValueError("Duty không được giảm khi nhiệt độ tăng.")
        if self.hysteresis_c < 0 or self.minimum_change < 0:
            raise ValueError("Hysteresis và minimum_change không được âm.")

    def target(self, temperature: float) -> int:
        if temperature <= self.points[0].temperature:
            return self.points[0].duty
        if temperature >= self.points[-1].temperature:
            return self.points[-1].duty
        for lower, upper in zip(self.points, self.points[1:]):
            if temperature <= upper.temperature:
                span = upper.temperature - lower.temperature
                ratio = (temperature - lower.temperature) / span
                return round(lower.duty + ratio * (upper.duty - lower.duty))
        return self.points[-1].duty

    def target_with_hysteresis(
        self,
        temperature: float,
        previous_temperature: float | None,
        previous_duty: int | None,
    ) -> int:
        requested = self.target(temperature)
        if previous_temperature is None or previous_duty is None:
            return requested
        cooling_inside_band = (
            temperature < previous_temperature
            and previous_temperature - temperature < self.hysteresis_c
        )
        if cooling_inside_band and requested < previous_duty:
            return previous_duty
        if abs(requested - previous_duty) < self.minimum_change:
            return previous_duty
        return requested

    @property
    def summary(self) -> str:
        return "  ·  ".join(
            f"{point.temperature:g}°C → {point.duty}%" for point in self.points
        )


@dataclass(frozen=True, slots=True)
class FanMode:
    key: str
    label: str
    description: str
    curve: FanCurve | None


@dataclass(frozen=True, slots=True)
class CurveDecision:
    requested_duty: int | None
    may_write: bool
    emergency: bool
    reason: str


def decide_curve_output(
    curve: FanCurve,
    temperature: float,
    sensor_age_seconds: float,
    stable_manual_control: bool,
    previous_temperature: float | None = None,
    previous_duty: int | None = None,
    stale_after_seconds: float = 5.0,
    emergency_temperature: float = 90.0,
) -> CurveDecision:
    if sensor_age_seconds < 0:
        raise ValueError("Tuổi dữ liệu cảm biến không được âm.")
    emergency = sensor_age_seconds > stale_after_seconds or temperature >= emergency_temperature
    requested = (
        100
        if emergency
        else curve.target_with_hysteresis(
            temperature, previous_temperature, previous_duty
        )
    )
    if not stable_manual_control:
        return CurveDecision(
            requested,
            False,
            emergency,
            "Capability gate khóa: stable manual fan control chưa được xác minh.",
        )
    if emergency:
        reason = (
            "Failsafe 100%: dữ liệu nhiệt độ đã stale."
            if sensor_age_seconds > stale_after_seconds
            else "Failsafe 100%: chạm ngưỡng nhiệt khẩn cấp."
        )
        return CurveDecision(100, True, True, reason)
    return CurveDecision(requested, True, False, "Curve output hợp lệ.")


def _curve(*points: tuple[float, int]) -> FanCurve:
    return FanCurve(tuple(CurvePoint(*point) for point in points))


CUSTOM_TEMPERATURES = (40.0, 55.0, 70.0, 80.0, 90.0)
DEFAULT_CUSTOM_DUTIES = (20, 35, 60, 80, 100)


def custom_curve(duties: tuple[int, ...]) -> FanCurve:
    if len(duties) != len(CUSTOM_TEMPERATURES):
        raise ValueError("Custom curve phải có đúng năm duty points.")
    return FanCurve(
        tuple(
            CurvePoint(temperature, duty)
            for temperature, duty in zip(CUSTOM_TEMPERATURES, duties)
        )
    )


FAN_MODES = (
    FanMode("auto", "Auto", "BIOS / EC tự quản lý; không phát lệnh quạt.", None),
    FanMode(
        "silent",
        "Silent",
        "Ưu tiên độ ồn thấp, vẫn tăng nhanh khi nhiệt độ cao.",
        _curve((35, 0), (50, 22), (65, 42), (75, 68), (85, 100)),
    ),
    FanMode(
        "balanced",
        "Balanced",
        "Cân bằng nhiệt độ, độ ồn và độ trễ đáp ứng.",
        _curve((35, 15), (50, 32), (65, 55), (75, 78), (85, 100)),
    ),
    FanMode(
        "performance",
        "Performance",
        "Tăng quạt sớm để giữ xung ổn định.",
        _curve((35, 28), (50, 48), (65, 72), (75, 90), (82, 100)),
    ),
    FanMode(
        "gaming",
        "Gaming",
        "Curve chủ động nhất cho tải CPU/GPU kéo dài.",
        _curve((35, 38), (50, 58), (62, 78), (72, 95), (80, 100)),
    ),
    FanMode(
        "custom",
        "Custom",
        "Curve năm điểm do người dùng cấu hình; vẫn bị capability gate bảo vệ.",
        custom_curve(DEFAULT_CUSTOM_DUTIES),
    ),
)

FAN_MODES_BY_KEY = {mode.key: mode for mode in FAN_MODES}

"""AWCC raw ABI policy; full-range support is NOT full-range hardware validation."""
from __future__ import annotations

from datetime import datetime, timezone
import math

from .models import SystemSnapshot

MODEL = "Alienware x17 R1"
BIOS = "1.27.0"
KERNEL = "7.0.0-38-generic"
DRIVER = "28A4134FBF8432C66D7C668"
CHANNELS = (1, 2, 3, 4)
RAW_MIN = 0
RAW_MAX = 255
LEVELS = range(RAW_MIN, RAW_MAX + 1)
ACTIVE_SECONDS = 60.0
HARD_SECONDS = 75.0
HEARTBEAT_SECONDS = 5.0
PROTOCOL = 1


class FanControlError(RuntimeError):
    pass


def valid_raw(raw) -> bool:
    return type(raw) is int and RAW_MIN <= raw <= RAW_MAX


def check_levels(levels: dict[int, int]) -> None:
    if (set(levels) != set(CHANNELS)
            or any(type(k) is not int or not valid_raw(v) for k, v in levels.items())
            or sum(v != 100 for v in levels.values()) > 1):
        raise FanControlError("Raw phải là số nguyên 0–255; tối đa một kênh khác 100, ba kênh còn lại giữ 100.")


def check_snapshot(
    state: SystemSnapshot, ac: bool, *, starting: bool = False,
    expected_profile: str | None = None, levels: dict[int, int] | None = None,
    baseline_hot: float | None = None, require_spinning: bool = False,
    now: datetime | None = None,
) -> float:
    if (state.model, state.bios_version, state.kernel) != (MODEL, BIOS, KERNEL):
        raise FanControlError("Model/BIOS/kernel ngoài cấu hình đã kiểm chứng.")
    if state.profile.provider not in {"alienware-wmi", "alienware_wmi"}:
        raise FanControlError("Sai provider AWCC.")
    if not ac or state.capabilities.external_awccd_controller:
        raise FanControlError("Mất AC hoặc controller khác đang hoạt động.")
    captured = state.captured_at
    if captured.tzinfo is None:
        raise FanControlError("Snapshot thiếu timezone/freshness.")
    age = ((now or datetime.now(timezone.utc)) - captured).total_seconds()
    if not math.isfinite(age) or not -1 <= age <= 3:
        raise FanControlError("Telemetry quá hạn.")
    sensors = {t.label: t for t in state.temperatures}
    if (len(sensors) != len(state.temperatures) or "CPU" not in sensors or "GPU" not in sensors
            or sensors["CPU"].source != "AWCC WMI" or sensors["GPU"].source != "NVIDIA NVML"):
        raise FanControlError("Cần CPU/AWCC và GPU/NVIDIA hợp lệ, không trùng cảm biến.")
    values = [t.celsius for t in state.temperatures]
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 10 <= v < 70 for v in values):
        raise FanControlError("Sensor lỗi hoặc nhiệt độ chạm 70 °C.")
    hot = max(values)
    # User-approved CPU startup relaxation only. Invalid/missing CPU telemetry,
    # the absolute 70 °C ceiling and runtime rise guards still apply to CPU.
    # Other sensors retain their original cold-start requirement.
    if starting and any(t.label != "CPU" and t.celsius > 50 for t in state.temperatures):
        raise FanControlError("Bắt đầu cần GPU và cảm biến ngoài CPU ≤50 °C; hãy hạ tải trước.")
    if baseline_hot is not None and hot - baseline_hot >= 10:
        raise FanControlError("Nhiệt độ tăng ≥10 °C; dừng và khôi phục.")
    if sorted(f.channel for f in state.awcc_fans) != list(CHANNELS):
        raise FanControlError("Topology bốn quạt AWCC thay đổi.")
    for fan in state.awcc_fans:
        if (type(fan.boost) is not int or not 0 <= fan.boost <= 255
                or type(fan.rpm) is not int or not 0 <= fan.rpm <= 20000
                or (require_spinning and fan.rpm == 0)):
            raise FanControlError("RPM/boost không hợp lệ hoặc quạt dừng sau settle.")
    if len(state.fans) != 4 or any(f.pwm_enable != 2 for f in state.fans):
        raise FanControlError("Trạng thái SMM BIOS-auto thay đổi; không thử takeover.")
    if expected_profile is not None and state.profile.current != expected_profile:
        raise FanControlError("Thermal profile thay đổi ngoài phiên.")
    if levels is not None and {f.channel: f.boost for f in state.awcc_fans} != levels:
        raise FanControlError("Boost đọc lại không khớp phiên.")
    return hot

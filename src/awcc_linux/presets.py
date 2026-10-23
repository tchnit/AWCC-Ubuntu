from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Preset:
    key: str
    label: str
    description: str
    profile: str | None


PRESETS = (
    Preset(
        "auto",
        "Auto",
        "Theo trạng thái hệ thống hiện tại; không tự ghi profile khi ứng dụng mở.",
        None,
    ),
    Preset(
        "balanced",
        "Balanced",
        "Yêu cầu profile balanced; BIOS / EC tiếp tục điều khiển quạt.",
        "balanced",
    ),
    Preset(
        "quiet",
        "Yên tĩnh",
        "Ghi Quiet qua helper, xác minh read-back 2,75 giây; không ghi PWM/boost.",
        "quiet",
    ),
    Preset(
        "performance",
        "Performance",
        "Ghi qua power-profiles-daemon, xác minh read-back 2 giây; không ghi PWM/boost.",
        "performance",
    ),
)

PRESETS_BY_KEY = {preset.key: preset for preset in PRESETS}

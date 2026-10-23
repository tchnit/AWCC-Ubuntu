from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ControlState(str, Enum):
    UNAVAILABLE = "unavailable"
    BIOS_AUTO = "bios-auto"
    MANUAL = "manual"
    MIXED = "mixed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Temperature:
    channel: int
    label: str
    celsius: float
    source: str = "unknown"


@dataclass(frozen=True, slots=True)
class Fan:
    channel: int
    label: str
    rpm: int | None
    target_rpm: int | None = None
    pwm_enable: int | None = None

    @property
    def control_label(self) -> str:
        return {1: "Manual", 2: "BIOS / EC"}.get(self.pwm_enable, "Không xác định")


@dataclass(frozen=True, slots=True)
class AwccFan:
    """Fan channel exported by the native alienware_wmi AWCC interface."""

    channel: int
    label: str
    rpm: int | None
    min_rpm: int | None
    max_rpm: int | None
    boost: int | None
    temperature_channel: int | None = None

    @property
    def boost_percent(self) -> float | None:
        if self.boost is None:
            return None
        return self.boost * 100.0 / 255.0


@dataclass(frozen=True, slots=True)
class ProfileState:
    current: str | None
    choices: tuple[str, ...] = ()
    provider: str | None = None


@dataclass(frozen=True, slots=True)
class CapabilityReport:
    telemetry: bool
    platform_profiles: bool
    stable_manual_fan_control: bool
    control_state: ControlState
    reasons: tuple[str, ...] = ()
    awcc_fan_boost: bool = False
    external_awccd_controller: bool = False


@dataclass(frozen=True, slots=True)
class SystemSnapshot:
    captured_at: datetime
    model: str | None
    bios_version: str | None
    kernel: str
    profile: ProfileState
    fans: tuple[Fan, ...] = ()
    awcc_fans: tuple[AwccFan, ...] = ()
    temperatures: tuple[Temperature, ...] = ()
    capabilities: CapabilityReport = field(
        default_factory=lambda: CapabilityReport(
            False, False, False, ControlState.UNAVAILABLE
        )
    )
    warnings: tuple[str, ...] = ()

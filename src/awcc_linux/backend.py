from __future__ import annotations

import platform
import math
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable

from .discovery import SysfsPaths, discover
from .models import (
    AwccFan,
    CapabilityReport,
    ControlState,
    Fan,
    ProfileState,
    SystemSnapshot,
    Temperature,
)


_CHANNEL_RE = re.compile(r"^(?:fan|temp)(\d+)_")
_NVIDIA_TEMPERATURE_COMMAND = (
    "nvidia-smi",
    "--query-gpu=temperature.gpu",
    "--format=csv,noheader,nounits",
)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def _read_int(path: Path) -> int | None:
    value = _read_text(path)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _channels(root: Path, pattern: str) -> list[int]:
    channels: set[int] = set()
    try:
        files = root.glob(pattern)
    except OSError:
        return []
    for path in files:
        match = _CHANNEL_RE.match(path.name)
        if match:
            channels.add(int(match.group(1)))
    return sorted(channels)


def _read_nvidia_temperatures() -> tuple[Temperature, ...]:
    """Read GPU temperatures from NVML through nvidia-smi, when available.

    Some x17 R1 firmware/driver combinations label a WMI channel as GPU while
    reporting an impossible value (for example 2 °C).  NVIDIA is the
    authoritative source for an enabled NVIDIA dGPU, and the command is
    diagnostic/read-only.  Absence or failure deliberately degrades to no
    NVIDIA sample so ordinary sysfs telemetry remains available.
    """

    if shutil.which("nvidia-smi") is None:
        return ()
    try:
        completed = subprocess.run(
            _NVIDIA_TEMPERATURE_COMMAND,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    if completed.returncode != 0:
        return ()

    temperatures: list[Temperature] = []
    for index, value in enumerate(completed.stdout.splitlines()):
        try:
            celsius = float(value.strip())
        except ValueError:
            continue
        if not 0 <= celsius <= 125:
            continue
        label = "GPU" if len(completed.stdout.splitlines()) == 1 else f"GPU {index}"
        temperatures.append(Temperature(index + 1, label, celsius, "NVIDIA NVML"))
    return tuple(temperatures)


class HardwareBackend:
    """Read-only hardware backend.

    Mutations deliberately do not live in this class. A future privileged helper
    must expose a narrow API and verify every write by reading state back.
    """

    def __init__(
        self,
        sys_root: Path = Path("/sys"),
        runtime_root: Path = Path("/"),
        nvidia_temperature_reader: Callable[[], tuple[Temperature, ...]] | None = None,
    ) -> None:
        self.sys_root = sys_root
        self.runtime_root = runtime_root
        self.nvidia_temperature_reader = nvidia_temperature_reader

    def _paths(self) -> SysfsPaths:
        return discover(self.sys_root)

    def _read_profile(self, root: Path | None) -> ProfileState:
        if root is None:
            return ProfileState(None)
        current = _read_text(root / "profile")
        choices = tuple((_read_text(root / "choices") or "").split())
        return ProfileState(current, choices, _read_text(root / "name"))

    def _read_fans(self, root: Path | None) -> tuple[Fan, ...]:
        if root is None:
            return ()
        fans: list[Fan] = []
        for channel in _channels(root, "fan*_input"):
            fans.append(
                Fan(
                    channel=channel,
                    label=_read_text(root / f"fan{channel}_label") or f"Fan {channel}",
                    rpm=_read_int(root / f"fan{channel}_input"),
                    target_rpm=_read_int(root / f"fan{channel}_target"),
                    pwm_enable=_read_int(root / f"pwm{channel}_enable"),
                )
            )
        return tuple(fans)

    def _read_temperatures(
        self, root: Path | None, source: str
    ) -> tuple[Temperature, ...]:
        if root is None:
            return ()
        temperatures: list[Temperature] = []
        for channel in _channels(root, "temp*_input"):
            raw = _read_int(root / f"temp{channel}_input")
            if raw is None:
                continue
            temperatures.append(
                Temperature(
                    channel,
                    _read_text(root / f"temp{channel}_label") or f"Sensor {channel}",
                    raw / 1000.0,
                    source,
                )
            )
        return tuple(temperatures)

    @staticmethod
    def _merge_temperatures(
        *sources: tuple[Temperature, ...],
    ) -> tuple[Temperature, ...]:
        """Prefer the first source for each label and retain unique sensors."""

        merged: list[Temperature] = []
        labels: set[str] = set()
        for source in sources:
            for sensor in source:
                key = sensor.label.casefold()
                if key not in labels:
                    merged.append(sensor)
                    labels.add(key)
        return tuple(merged)

    def _read_awcc_fans(self, root: Path | None) -> tuple[AwccFan, ...]:
        if root is None:
            return ()
        fans: list[AwccFan] = []
        for channel in _channels(root, "fan*_input"):
            fans.append(
                AwccFan(
                    channel=channel,
                    label=_read_text(root / f"fan{channel}_label") or f"Fan {channel}",
                    rpm=_read_int(root / f"fan{channel}_input"),
                    min_rpm=_read_int(root / f"fan{channel}_min"),
                    max_rpm=_read_int(root / f"fan{channel}_max"),
                    boost=_read_int(root / f"fan{channel}_boost"),
                    temperature_channel=_read_int(
                        root / f"pwm{channel}_auto_channels_temp"
                    ),
                )
            )
        return tuple(fans)

    @staticmethod
    def _capabilities(
        paths: SysfsPaths,
        profile: ProfileState,
        fans: tuple[Fan, ...],
        awcc_fans: tuple[AwccFan, ...],
        temperatures: tuple[Temperature, ...],
        external_awccd_controller: bool,
    ) -> CapabilityReport:
        reasons: list[str] = []
        if external_awccd_controller:
            reasons.append(
                "Phát hiện socket awccd: controller root bên ngoài có thể ghi profile và fan boost."
            )
        enable_values = [fan.pwm_enable for fan in fans if fan.pwm_enable is not None]
        if not fans and awcc_fans:
            state = ControlState.UNKNOWN
            reasons.append(
                "AWCC có telemetry quạt nhưng không công bố trạng thái takeover kiểu dell_smm."
            )
        elif not fans:
            state = ControlState.UNAVAILABLE
            reasons.append("Không tìm thấy telemetry quạt từ AWCC hoặc dell_smm.")
        elif not enable_values:
            state = ControlState.UNKNOWN
            reasons.append("Driver không công bố trạng thái pwm_enable.")
        elif all(value == 2 for value in enable_values):
            state = ControlState.BIOS_AUTO
            reasons.append("Tất cả kênh pwm_enable đang ở 2 (BIOS/automatic).")
        elif all(value == 1 for value in enable_values):
            state = ControlState.MANUAL
            reasons.append("Driver báo manual, nhưng cần kiểm chứng khả năng duy trì trước khi điều khiển.")
        else:
            state = ControlState.MIXED
            reasons.append("Các kênh quạt đang có trạng thái điều khiển không đồng nhất.")

        # Even a current value of 1 is not sufficient evidence of stable takeover.
        stable_manual = False
        if paths.dell_smm_hwmon is not None:
            if len(enable_values) > 1:
                reasons.append(
                    "Driver đang công bố per-fan auto state; không thấy global SMM takeover."
                )
            reasons.append("Stable manual takeover chưa được backend xác minh.")

        awcc_boost = bool(awcc_fans) and all(fan.boost is not None for fan in awcc_fans)
        if awcc_boost:
            reasons.append(
                "alienware_wmi công bố AWCC fan boost 0–255; write/read-back đã hoạt động "
                "nhưng chưa có bằng chứng RPM/takeover ổn định. Custom thermal profile "
                "không cung cấp fan curve hoặc manual RPM."
            )

        return CapabilityReport(
            telemetry=bool(fans or awcc_fans or temperatures),
            platform_profiles=profile.current is not None and bool(profile.choices),
            stable_manual_fan_control=stable_manual,
            control_state=state,
            reasons=tuple(reasons),
            awcc_fan_boost=awcc_boost,
            external_awccd_controller=external_awccd_controller,
        )

    def _external_awccd_controller_active(self) -> bool:
        """Detect the known competing daemon without connecting to or controlling it."""

        try:
            return (self.runtime_root / "run/awcc/awccd.sock").is_socket()
        except OSError:
            return False

    def snapshot(self) -> SystemSnapshot:
        paths = self._paths()
        profile_state = self._read_profile(paths.platform_profile)
        # dell_smm has coherent fan/target/enable information and extra sensors.
        fans = self._read_fans(paths.dell_smm_hwmon)
        awcc_fans = self._read_awcc_fans(paths.alienware_hwmon)
        awcc_temperatures = self._read_temperatures(paths.alienware_hwmon, "AWCC WMI")
        dell_temperatures = self._read_temperatures(paths.dell_smm_hwmon, "dell_smm")
        nvidia_temperatures = (
            self.nvidia_temperature_reader()
            if self.nvidia_temperature_reader is not None
            else _read_nvidia_temperatures()
            if self.sys_root == Path("/sys")
            else ()
        )
        warnings: list[str] = []
        def valid_samples(samples):
            valid = []
            for sensor in samples:
                # The affected x17 firmware has reported its GPU at 2--3 C.
                plausible = math.isfinite(sensor.celsius) and 0 <= sensor.celsius <= 125
                if "gpu" in sensor.label.casefold() and sensor.source != "NVIDIA NVML":
                    plausible = plausible and sensor.celsius >= 10
                if plausible:
                    valid.append(sensor)
                else:
                    warnings.append(f"{sensor.label}: bỏ qua dữ liệu không đáng tin từ {sensor.source}.")
            return tuple(valid)
        # Validate before merging: a bad preferred channel must not hide a
        # valid secondary sensor with the same label.
        temperatures = self._merge_temperatures(
            valid_samples(nvidia_temperatures), valid_samples(awcc_temperatures),
            valid_samples(dell_temperatures),
        )
        if not any("gpu" in sensor.label.casefold() for sensor in temperatures):
            warnings.append("GPU: không có dữ liệu nhiệt độ hợp lệ.")
        external_awccd_controller = self._external_awccd_controller_active()
        if external_awccd_controller:
            warnings.append(
                "Phát hiện awccd đang chạy: profile/fan boost có thể bị controller bên ngoài ghi đè."
            )
        if paths.alienware_hwmon is None:
            warnings.append("Không tìm thấy alienware_wmi hwmon.")
        if paths.dell_smm_hwmon is None:
            warnings.append("Không tìm thấy dell_smm hwmon.")
        if paths.platform_profile is None:
            warnings.append("Không tìm thấy alienware_wmi platform profile.")

        dmi = self.sys_root / "class/dmi/id"
        return SystemSnapshot(
            captured_at=datetime.now().astimezone(),
            model=_read_text(dmi / "product_name"),
            bios_version=_read_text(dmi / "bios_version"),
            kernel=platform.release(),
            profile=profile_state,
            fans=fans,
            awcc_fans=awcc_fans,
            temperatures=temperatures,
            capabilities=self._capabilities(
                paths,
                profile_state,
                fans,
                awcc_fans,
                temperatures,
                external_awccd_controller,
            ),
            warnings=tuple(warnings),
        )

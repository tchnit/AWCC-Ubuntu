from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .backend import HardwareBackend
from .discovery import discover


@dataclass(frozen=True, slots=True)
class GateCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class PreflightReport:
    checks: tuple[GateCheck, ...]

    @property
    def ready(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> tuple[GateCheck, ...]:
        return tuple(check for check in self.checks if not check.passed)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


class ExperimentPreflight:
    """Read-only gate for the experimental driver test.

    Passing this gate is necessary, not permission to execute the experiment.
    No method in this class writes sysfs or manipulates modules.
    """

    def __init__(
        self,
        sys_root: Path = Path("/sys"),
        candidate: Path = Path("research/module/dell-smm-hwmon-x17r1.ko"),
        temperature_limit_c: float = 60.0,
    ) -> None:
        self.sys_root = sys_root
        self.candidate = candidate
        self.temperature_limit_c = temperature_limit_c

    def _ac_online(self) -> tuple[bool, str]:
        supplies = self.sys_root / "class/power_supply"
        mains: list[str] = []
        try:
            candidates = supplies.iterdir()
        except OSError:
            return False, "Không đọc được power supplies."
        for supply in candidates:
            if _read(supply / "type") == "Mains":
                status = _read(supply / "online")
                mains.append(f"{supply.name}={status}")
                if status == "1":
                    return True, f"AC online ({supply.name})."
        return False, "Không có AC online: " + (", ".join(mains) or "không tìm thấy Mains")

    def run(self) -> PreflightReport:
        paths = discover(self.sys_root)
        snapshot = HardwareBackend(self.sys_root).snapshot()
        dmi = self.sys_root / "class/dmi/id"
        vendor = _read(dmi / "sys_vendor")
        model = _read(dmi / "product_name")
        ac_ok, ac_detail = self._ac_online()
        temperatures = [item.celsius for item in snapshot.temperatures]
        hottest = max(temperatures, default=999.0)
        enables = [fan.pwm_enable for fan in snapshot.fans]

        checks = (
            GateCheck(
                "exact-model",
                vendor == "Alienware" and model == "Alienware x17 R1",
                f"vendor={vendor!r}, model={model!r}",
            ),
            GateCheck("ac-power", ac_ok, ac_detail),
            GateCheck(
                "stock-module-loaded",
                (self.sys_root / "module/dell_smm_hwmon").is_dir(),
                "dell_smm_hwmon hiện diện trong /sys/module.",
            ),
            GateCheck(
                "dell-smm-telemetry",
                paths.dell_smm_hwmon is not None and len(snapshot.fans) == 4,
                f"fans={len(snapshot.fans)}",
            ),
            GateCheck(
                "bios-auto-baseline",
                len(enables) == 4 and all(value == 2 for value in enables),
                f"pwm_enable={enables}",
            ),
            GateCheck(
                "temperature-headroom",
                bool(temperatures) and hottest <= self.temperature_limit_c,
                f"max={hottest:.1f} °C, limit={self.temperature_limit_c:.1f} °C",
            ),
            GateCheck(
                "balanced-profile",
                snapshot.profile.current == "balanced",
                f"profile={snapshot.profile.current!r}",
            ),
            GateCheck(
                "candidate-present",
                self.candidate.is_file(),
                str(self.candidate),
            ),
        )
        return PreflightReport(checks)

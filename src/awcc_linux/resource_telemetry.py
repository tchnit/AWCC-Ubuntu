"""Unprivileged desktop resource telemetry; never part of the control helper."""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import shutil
import subprocess

from .models import SystemSnapshot


@dataclass(frozen=True, slots=True)
class ResourceMetrics:
    cpu_mhz: float | None = None
    cpu_percent: float | None = None
    gpu_mhz: float | None = None
    gpu_percent: float | None = None
    ram_used_bytes: int | None = None
    ram_total_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    hardware: SystemSnapshot
    resources: ResourceMetrics


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""


def _number(value: str, maximum: float) -> float | None:
    try:
        number = float(value.strip())
    except ValueError:
        return None
    return number if math.isfinite(number) and 0 <= number <= maximum else None


class ResourceReader:
    """Sample counters without sleeping; first CPU utilization is unknown."""

    def __init__(self, proc_root: Path = Path("/proc"), sys_root: Path = Path("/sys")):
        self.proc_root = proc_root
        self.sys_root = sys_root
        self._previous_cpu: tuple[int, int] | None = None

    def _cpu_percent(self) -> float | None:
        lines = _read(self.proc_root / "stat").splitlines()
        aggregate = next((line.split()[1:] for line in lines if line.startswith("cpu ")), [])
        try:
            counters = tuple(int(value) for value in aggregate[:8])
        except ValueError:
            counters = ()
        if len(counters) < 4 or any(value < 0 for value in counters):
            self._previous_cpu = None
            return None
        total = sum(counters)  # guest/guest_nice already included in user/nice.
        idle = counters[3] + (counters[4] if len(counters) > 4 else 0)
        previous, self._previous_cpu = self._previous_cpu, (total, idle)
        if previous is None:
            return None
        delta_total, delta_idle = total - previous[0], idle - previous[1]
        if delta_total <= 0 or not 0 <= delta_idle <= delta_total:
            return None
        return 100.0 * (delta_total - delta_idle) / delta_total

    def _cpu_mhz(self) -> float | None:
        frequencies = []
        for path in (self.sys_root / "devices/system/cpu").glob("cpu[0-9]*/cpufreq/scaling_cur_freq"):
            khz = _number(_read(path), 10_000_000)
            if khz is not None and khz > 0:
                frequencies.append(khz / 1000)
        if not frequencies:
            for line in _read(self.proc_root / "cpuinfo").splitlines():
                key, separator, value = line.partition(":")
                if separator and key.strip() == "cpu MHz":
                    mhz = _number(value, 10_000)
                    if mhz is not None and mhz > 0:
                        frequencies.append(mhz)
        return sum(frequencies) / len(frequencies) if frequencies else None

    def _memory(self) -> tuple[int | None, int | None]:
        values = {}
        for line in _read(self.proc_root / "meminfo").splitlines():
            fields = line.split()
            if len(fields) != 3 or fields[2] != "kB":
                continue
            try:
                value = int(fields[1])
            except ValueError:
                continue
            if value >= 0:
                values[fields[0].rstrip(":")] = value * 1024
        total, available = values.get("MemTotal"), values.get("MemAvailable")
        if total is None or total <= 0:
            return None, None
        if available is None or available > total:
            return None, total
        return total - available, total

    def _gpu(self) -> tuple[float | None, float | None]:
        if shutil.which("nvidia-smi") is None:
            return None, None
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=clocks.current.graphics,utilization.gpu",
                 "--format=csv,noheader,nounits", "--id=0"],
                check=False, capture_output=True, text=True, timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None, None
        lines = result.stdout.strip().splitlines()
        if result.returncode != 0 or len(lines) != 1:
            return None, None
        fields = lines[0].split(",")
        if len(fields) != 2:
            return None, None
        return _number(fields[0], 10_000), _number(fields[1], 100)

    def read(self) -> ResourceMetrics:
        percent = self._cpu_percent()
        frequency = self._cpu_mhz()
        used, total = self._memory()
        gpu_frequency, gpu_percent = self._gpu()
        return ResourceMetrics(frequency, percent, gpu_frequency, gpu_percent, used, total)

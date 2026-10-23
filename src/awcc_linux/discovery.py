from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ALIENWARE_PLATFORM_PROFILE_PROVIDERS = frozenset({"alienware-wmi", "alienware_wmi"})


@dataclass(frozen=True, slots=True)
class SysfsPaths:
    alienware_hwmon: Path | None
    dell_smm_hwmon: Path | None
    platform_profile: Path | None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def find_hwmon(hwmon_root: Path, expected_name: str) -> Path | None:
    """Find a hwmon provider by name; hwmon indices are not stable."""
    try:
        candidates = sorted(hwmon_root.glob("hwmon*"))
    except OSError:
        return None
    for candidate in candidates:
        if _read_text(candidate / "name") == expected_name:
            return candidate
    return None


def find_platform_profile(
    platform_root: Path,
    providers: frozenset[str] | None = None,
) -> Path | None:
    """Find a platform-profile provider, optionally requiring its driver name.

    More than one provider can expose this class on a system.  A control center
    for Alienware must never select an unrelated provider merely because its
    directory sorts first.
    """

    try:
        candidates = sorted(platform_root.glob("platform-profile-*"))
    except OSError:
        return None
    for candidate in candidates:
        if not (candidate / "profile").is_file():
            continue
        if providers is None or _read_text(candidate / "name") in providers:
            return candidate
    return None


def discover(
    sys_root: Path = Path("/sys"),
) -> SysfsPaths:
    return SysfsPaths(
        alienware_hwmon=find_hwmon(sys_root / "class/hwmon", "alienware_wmi"),
        dell_smm_hwmon=find_hwmon(sys_root / "class/hwmon", "dell_smm"),
        platform_profile=find_platform_profile(
            sys_root / "class/platform-profile",
            ALIENWARE_PLATFORM_PROFILE_PROVIDERS,
        ),
    )

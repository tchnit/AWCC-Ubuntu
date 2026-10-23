from __future__ import annotations

import time
import subprocess
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .discovery import ALIENWARE_PLATFORM_PROFILE_PROVIDERS, find_platform_profile
from .profile_policy import profile_block_reason
from .profile_recovery import PLATFORM_TO_DAEMON, SINGLETON, acquire_singleton, daemon_profile, restore_daemon


SAFE_PROFILES = frozenset(
    {"low-power", "quiet", "balanced", "balanced-performance", "performance", "custom"}
)


class ProfileControlError(RuntimeError):
    """A platform-profile request could not be validated or verified."""


@dataclass(frozen=True, slots=True)
class ProfileChangeResult:
    requested: str
    previous: str
    observed: tuple[str, ...]
    restored: bool | None = None
    restored_profile: str | None = None
    error: str = ""

    @property
    def persistent(self) -> bool:
        return not self.error and bool(self.observed) and all(value == self.requested for value in self.observed)

    @property
    def final(self) -> str | None:
        return self.restored_profile if self.restored is not None else (self.observed[-1] if self.observed else self.previous)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ProfileControlError(f"Không đọc được {path}: {exc}") from exc


def _read_optional(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


class ProfileController:
    """Narrow writer for the kernel platform-profile ABI.

    The caller is responsible for privilege separation. This class validates the
    provider, advertised choices and a conservative application allow-list, then
    verifies the state repeatedly after the write.
    """

    def __init__(
        self,
        sys_root: Path = Path("/sys"),
        sleeper: Callable[[float], None] = time.sleep,
        daemon_runner: Callable | None = None,
        lock_path: Path | None = None,
        runtime_root: Path = Path("/"),
    ) -> None:
        self.sys_root = sys_root
        self.sleeper = sleeper
        self.daemon_runner = daemon_runner or (subprocess.run if sys_root == Path("/sys") else None)
        self.lock_path = lock_path if lock_path is not None else (SINGLETON if sys_root == Path("/sys") else None)
        self.runtime_root = runtime_root

    def _assert_no_controller(self) -> None:
        from .backend import HardwareBackend
        if HardwareBackend(self.sys_root, self.runtime_root)._external_awccd_controller_active():
            raise ProfileControlError("awccd đang điều khiển máy; không ghi profile.")
        if self.sys_root == Path("/sys"):
            for unit in ("awccd.service", "i8kmon.service"):
                try:
                    status = subprocess.run(["/usr/bin/systemctl", "is-active", unit], capture_output=True, text=True, timeout=5)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    raise ProfileControlError(f"Không xác minh được controller {unit}: {exc}") from exc
                if status.stdout.strip() != "inactive":
                    raise ProfileControlError(f"Controller cạnh tranh: {unit}.")

    def _profile_root(self) -> Path:
        root = find_platform_profile(
            self.sys_root / "class/platform-profile",
            ALIENWARE_PLATFORM_PROFILE_PROVIDERS,
        )
        if root is None:
            raise ProfileControlError("Không tìm thấy platform-profile đang hoạt động.")
        return root

    def _validate_custom(self) -> None:
        from .backend import HardwareBackend
        state = HardwareBackend(self.sys_root).snapshot()
        temps = {t.label: t.celsius for t in state.temperatures}
        ac = list((self.sys_root / "class/power_supply").glob("AC*/online"))
        if not {"CPU", "GPU"} <= temps.keys() or max(temps.values()) > 50:
            raise ProfileControlError("Custom thermal cần cảm biến CPU/GPU hợp lệ và nhiệt độ ≤ 50 °C; chọn Tiết kiệm trước để hạ nhiệt.")
        if not any(_read_optional(path) == "1" for path in ac):
            raise ProfileControlError("Custom thermal cần nguồn AC.")
        if state.capabilities.external_awccd_controller or len(state.fans) != 4 or any(f.pwm_enable != 2 for f in state.fans):
            raise ProfileControlError("Custom thermal cần bốn quạt ở BIOS auto và không có controller cạnh tranh.")

    def set_profile(
        self,
        requested: str,
        verification_delays: Iterable[float] = (0.0, 0.75, 2.0),
    ) -> ProfileChangeResult:
        if self.lock_path is None:
            return self._set_profile_locked(requested, verification_delays)
        try:
            fd = acquire_singleton(self.lock_path)
        except (OSError, RuntimeError) as exc:
            raise ProfileControlError(f"Không lấy được lock profile/fan: {exc}") from exc
        try:
            return self._set_profile_locked(requested, verification_delays)
        finally:
            os.close(fd)

    def _set_profile_locked(
        self, requested: str, verification_delays: Iterable[float],
    ) -> ProfileChangeResult:
        if requested not in SAFE_PROFILES:
            raise ProfileControlError(f"Profile không nằm trong allow-list: {requested!r}")
        delays = tuple(verification_delays)
        if not delays or any(delay < 0 for delay in delays):
            raise ProfileControlError("Cửa sổ xác minh không hợp lệ.")

        root = self._profile_root()
        provider = _read(root / "name")
        if provider not in {"alienware-wmi", "alienware_wmi"}:
            raise ProfileControlError(f"Provider không được hỗ trợ: {provider!r}")

        choices = set(_read(root / "choices").split())
        if requested not in choices:
            raise ProfileControlError(f"Firmware không công bố profile {requested!r}.")

        dmi = self.sys_root / "class/dmi/id"
        blocked = profile_block_reason(
            _read_optional(dmi / "product_name"),
            _read_optional(dmi / "bios_version"),
            requested,
        )
        if blocked is not None:
            raise ProfileControlError(blocked)

        self._assert_no_controller()
        if requested == "custom":
            self._validate_custom()

        profile_path = root / "profile"
        previous = _read(profile_path)
        if previous not in SAFE_PROFILES:
            raise ProfileControlError("Profile hiện tại chưa có đường khôi phục an toàn.")
        # Normal profile recovery goes through PPD if PPD is available. In
        # particular, Performance must never be restored via unverified sysfs.
        previous_daemon = None
        if self.daemon_runner is not None and previous in PLATFORM_TO_DAEMON:
            try:
                previous_daemon = daemon_profile(self.daemon_runner)
            except ProfileControlError:
                raise
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                previous_daemon = None
            if previous_daemon is not None and previous_daemon != PLATFORM_TO_DAEMON[previous]:
                raise ProfileControlError("PPD và profile hiện tại không đồng nhất.")
        if previous_daemon is None:
            previous_blocked = profile_block_reason(
                _read_optional(dmi / "product_name"), _read_optional(dmi / "bios_version"), previous,
            )
            if previous_blocked:
                raise ProfileControlError("Không có đường khôi phục profile ban đầu đã xác minh.")
        observed: list[str] = []
        try:
            self._assert_no_controller()
            profile_path.write_text(f"{requested}\n", encoding="utf-8")
            for delay in delays:
                if delay > 0:
                    self.sleeper(delay)
                self._assert_no_controller()
                observed.append(_read(profile_path))
            if all(value == requested for value in observed):
                return ProfileChangeResult(requested, previous, tuple(observed))
            error = "Profile không giữ ổn định trong cửa sổ xác minh."
        except (OSError, ProfileControlError) as exc:
            error = str(exc)

        restored = False
        final = None
        try:
            if previous_daemon is not None:
                restored, final = restore_daemon(
                    previous_daemon, previous, lambda: _read_optional(profile_path),
                    self.daemon_runner, self.sleeper,
                )
            else:
                recovery_target = previous
                if previous == "custom":
                    try:
                        self._validate_custom()
                    except ProfileControlError:
                        recovery_target = "balanced"
                        error += " Custom không còn đủ điều kiện; chuyển về Balanced an toàn."
                profile_path.write_text(f"{recovery_target}\n", encoding="utf-8")
                restored = True
                for delay in delays:
                    if delay:
                        self.sleeper(delay)
                    final = _read_optional(profile_path)
                    restored = restored and final == recovery_target
                restored = restored and recovery_target == previous
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            error += f" Khôi phục thất bại: {exc}."
        final = _read_optional(profile_path)
        return ProfileChangeResult(requested, previous, tuple(observed), restored, final, error)

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from .discovery import ALIENWARE_PLATFORM_PROFILE_PROVIDERS, find_platform_profile
from .profile_recovery import (
    PLATFORM_TO_DAEMON, DAEMON_TO_PLATFORM, VERIFICATION_DELAYS,
    daemon_profile, verify_routes, restore_daemon,
)
from .helper_integrity import helper_payload_reason
from .profile_policy import profile_block_reason


# The x17 R1 test machine accepted power-saver initially, then reverted to
# balanced after roughly 1.2 seconds.  An immediate read-back is therefore not
# evidence that a profile is stable.  These are incremental delays and cover a
# two-second observation window without blocking the GTK thread.


def profile_observations_are_stable(target: str, observed: tuple[str, ...]) -> bool:
    """Only accept a request when every timed read-back matches the target."""

    return bool(observed) and all(value == target for value in observed)


def profile_routes_are_stable(
    daemon_target: str,
    platform_target: str,
    daemon_observed: tuple[str, ...],
    platform_observed: tuple[str | None, ...],
) -> bool:
    """Require PPD and the actual Alienware platform-profile to agree.

    A successful D-Bus request alone does not establish that the Alienware
    driver accepted the corresponding platform profile.
    """

    return (
        len(daemon_observed) == len(VERIFICATION_DELAYS)
        and len(platform_observed) == len(VERIFICATION_DELAYS)
        and profile_observations_are_stable(daemon_target, daemon_observed)
        and all(value == platform_target for value in platform_observed)
    )


def _read_alienware_platform_profile() -> str | None:
    root = find_platform_profile(
        Path("/sys/class/platform-profile"),
        ALIENWARE_PLATFORM_PROFILE_PROVIDERS,
    )
    if root is None:
        return None
    try:
        return (root / "profile").read_text(encoding="utf-8").strip() or None
    except (OSError, UnicodeError):
        return None


HELPER_BASELINES = frozenset({"quiet", "balanced-performance", "custom"})


def _restore_helper_profile(profile: str) -> bool:
    if profile not in HELPER_BASELINES | {"balanced"}:
        return False
    if helper_payload_reason() is not None:
        return False
    from .privileged import HELPER_PATH, HELPER_TIMEOUT, ProfileClient
    client = ProfileClient()
    if not client.available:
        return False
    result = subprocess.run(
        ["pkexec", str(HELPER_PATH), "set-profile", profile],
        check=False, capture_output=True, text=True, timeout=HELPER_TIMEOUT,
    )
    return client._parse_result(result).ok


def _restore_quiet() -> bool:
    return _restore_helper_profile("quiet")


@dataclass(frozen=True, slots=True)
class PowerProfilesState:
    available: bool = False
    active: str | None = None
    profiles: tuple[str, ...] = ()
    performance_degraded: str = ""

    def supports_platform_profile(self, profile: str) -> bool:
        target = PLATFORM_TO_DAEMON.get(profile)
        return self.available and target is not None and target in self.profiles

    def block_reason(self, profile: str) -> str | None:
        target = PLATFORM_TO_DAEMON.get(profile)
        if target is None:
            return "power-profiles-daemon không quản lý profile này."
        if target not in self.profiles:
            return f"power-profiles-daemon không công bố mode {target}."
        return None

    def warning(self, profile: str) -> str | None:
        target = PLATFORM_TO_DAEMON.get(profile)
        if target == "performance" and self.performance_degraded:
            return f"Performance có thể bị giới hạn: {self.performance_degraded}."
        return None


@dataclass(frozen=True, slots=True)
class PowerProfileResult:
    ok: bool
    message: str
    final_profile: str | None = None


class PowerProfilesClient:
    """D-Bus state plus asynchronous powerprofilesctl mutations."""

    def __init__(
        self,
        platform_profile_reader: Callable[[], str | None] = _read_alienware_platform_profile,
    ) -> None:
        self.busy = False
        self._platform_profile_reader = platform_profile_reader
        self.proxy: Gio.DBusProxy | None = None
        try:
            self.proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SYSTEM,
                Gio.DBusProxyFlags.NONE,
                None,
                "net.hadess.PowerProfiles",
                "/net/hadess/PowerProfiles",
                "net.hadess.PowerProfiles",
                None,
            )
        except GLib.Error:
            self.proxy = None
        self.state = self._read_state()
        if self.proxy is not None:
            self.proxy.connect("g-properties-changed", self._properties_changed)

    @staticmethod
    def _unpack(proxy: Gio.DBusProxy, name: str, fallback):
        value = proxy.get_cached_property(name)
        return fallback if value is None else value.unpack()

    def _read_state(self) -> PowerProfilesState:
        if self.proxy is None:
            return PowerProfilesState()
        active = self._unpack(self.proxy, "ActiveProfile", "")
        raw_profiles = self._unpack(self.proxy, "Profiles", [])
        profiles = tuple(
            str(item["Profile"])
            for item in raw_profiles
            if isinstance(item, dict) and "Profile" in item
        )
        degraded = self._unpack(self.proxy, "PerformanceDegraded", "")
        return PowerProfilesState(True, str(active) or None, profiles, str(degraded))

    def refresh(self) -> PowerProfilesState:
        self.state = self._read_state()
        return self.state

    def _properties_changed(self, *_args) -> None:
        self.refresh()

    def set_platform_profile(
        self,
        profile: str,
        callback: Callable[[PowerProfileResult], None],
    ) -> bool:
        if self.busy:
            return False
        target = PLATFORM_TO_DAEMON.get(profile)
        if target is None:
            callback(PowerProfileResult(False, "Mode không thuộc power-profiles-daemon."))
            return False
        reason = self.state.block_reason(profile)
        if reason is not None:
            callback(PowerProfileResult(False, reason))
            return False

        self.busy = True
        def worker() -> None:
            previous_target = previous_platform = None
            attempted = False
            final = None
            try:
                def dmi_value(name):
                    try:
                        return (Path("/sys/class/dmi/id") / name).read_text().strip()
                    except OSError:
                        return None
                blocked = profile_block_reason(dmi_value("product_name"), dmi_value("bios_version"), profile, verified_ppd_route=True)
                if blocked:
                    raise RuntimeError(blocked)
                # Capture live state, not potentially stale D-Bus cache.
                previous_target = daemon_profile(subprocess.run)
                previous_platform = self._platform_profile_reader()
                if previous_platform != DAEMON_TO_PLATFORM[previous_target]:
                    if previous_platform not in HELPER_BASELINES or helper_payload_reason() is not None:
                        raise RuntimeError("PPD/platform không đồng nhất và chưa có đường khôi phục đã xác minh.")
                attempted = True
                if target == previous_target and previous_platform in HELPER_BASELINES and profile != "balanced":
                    # PPD can retain its last CPU mode for nonstandard thermal
                    # profiles. A same-value Set may skip the platform write.
                    # Go via the verified Balanced PPD route, then reapply the
                    # requested standard mode (never helper Performance/PWM).
                    bridged, _ = restore_daemon("balanced", "balanced", self._platform_profile_reader, subprocess.run, time.sleep)
                    if not bridged:
                        raise RuntimeError("Không xác minh được bước Balanced trước khi áp dụng lại mode chuẩn.")
                changed = subprocess.run(
                    ["powerprofilesctl", "set", target],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                if changed.returncode != 0:
                    raise RuntimeError(changed.stderr.strip() or "PPD từ chối đổi profile.")
                stable, final = verify_routes(target, profile, self._platform_profile_reader, subprocess.run, time.sleep)
                if not stable and profile == "balanced" and previous_platform in HELPER_BASELINES and daemon_profile(subprocess.run) == target:
                    # PPD can already call Balanced+ "balanced" and skip a
                    # same-value request. Finish the verified Balanced target
                    # through its helper without changing CPU power policy.
                    applied = _restore_helper_profile("balanced")
                    stable, final = verify_routes(target, profile, self._platform_profile_reader, subprocess.run, time.sleep)
                    stable = stable and applied
                if not stable:
                    raise RuntimeError("PPD và Alienware profile không giữ cùng giá trị trong đủ bốn mẫu.")
                result = PowerProfileResult(
                    True,
                    f"Mode {target} giữ cả PPD và Alienware profile qua đủ bốn mẫu trong 2 giây.",
                    final,
                )
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                recovery = "Chưa gửi lệnh đổi profile."
                if attempted:
                    try:
                        if previous_platform in HELPER_BASELINES:
                            # First restore the CPU policy if it changed. Low
                            # Power is now independently verified through PPD.
                            # Then restore the nonstandard thermal baseline.
                            if daemon_profile(subprocess.run) != previous_target:
                                cpu_restored, _ = restore_daemon(previous_target, DAEMON_TO_PLATFORM[previous_target], self._platform_profile_reader, subprocess.run, time.sleep)
                                if not cpu_restored:
                                    raise RuntimeError("Không xác minh được phục hồi CPU power policy ban đầu.")
                            restored = _restore_quiet() if previous_platform == "quiet" else _restore_helper_profile(previous_platform)
                            stable, final = verify_routes(previous_target, previous_platform, self._platform_profile_reader, subprocess.run, time.sleep)
                            restored = restored and stable
                        else:
                            restored, final = restore_daemon(
                                previous_target, DAEMON_TO_PLATFORM[previous_target],
                                self._platform_profile_reader, subprocess.run, time.sleep,
                            )
                        recovery = (
                            f"Đã khôi phục {previous_platform} và xác minh lại."
                            if restored else "Không xác minh được khôi phục; hãy kiểm tra profile hiện tại."
                        )
                    except (OSError, RuntimeError, subprocess.TimeoutExpired) as restore_error:
                        recovery = f"Khôi phục thất bại: {restore_error}."
                    # Never describe a pre-recovery sample as the final state.
                    final = self._platform_profile_reader()
                result = PowerProfileResult(False, f"Đổi profile thất bại: {exc}. {recovery}", final)
            GLib.idle_add(self._finish, callback, result)

        threading.Thread(target=worker, name="awcc-power-profile", daemon=True).start()
        return True

    def _finish(
        self,
        callback: Callable[[PowerProfileResult], None],
        result: PowerProfileResult,
    ) -> bool:
        self.busy = False
        self.refresh()
        callback(result)
        return GLib.SOURCE_REMOVE

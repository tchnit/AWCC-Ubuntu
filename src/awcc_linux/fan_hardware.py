"""Root-only AWCC port and independent process guardian. No PWM/raw SMM/EC API."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

from .backend import HardwareBackend
from .fan_policy import CHANNELS, DRIVER, HARD_SECONDS, HEARTBEAT_SECONDS, FanControlError, valid_raw
from .profile_recovery import SINGLETON, acquire_singleton


class NativeFanPort:
    def __init__(self):
        self.backend = HardwareBackend()
        paths = self.backend._paths()
        if paths.alienware_hwmon is None or paths.platform_profile is None:
            raise FanControlError("Thiếu AWCC sysfs provider.")
        self.hwmon = paths.alienware_hwmon
        self.profile = paths.platform_profile / "profile"
        self.directory = Path(tempfile.mkdtemp(prefix="awcc-fan-lease.", dir="/run"))
        self.fence = self.directory / "writes-fenced"
        self.recovering = self.directory / "recovering"
        self.verified = self.directory / "verified-restoration"
        self.custom_deadline = self.directory / "custom.deadline"
        self.heartbeat_deadline = self.directory / "heartbeat.deadline"
        self.startup_deadline = self.directory / "startup.deadline"
        self.original: str | None = None
        self.guardian: int | None = None
        self.audit_fd = os.open(self.directory / "audit.jsonl", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)

    def audit(self, event, **data):
        try:
            os.write(self.audit_fd, (json.dumps({"time": time.time(), "event": event, **data}) + "\n").encode())
        except OSError:
            pass  # Logging failure must not bypass restoration.

    @contextmanager
    def locked(self, name):
        with (self.directory / name).open("a") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            yield

    @staticmethod
    def command(*args, timeout=5):
        return subprocess.run(args, capture_output=True, text=True, check=False, timeout=timeout)

    def ensure_identity(self):
        if Path("/sys/module/alienware_wmi/srcversion").read_text().strip() != DRIVER:
            raise FanControlError("Driver đã đổi.")
        if Path("/sys/class/dmi/id/sys_vendor").read_text().strip() != "Alienware":
            raise FanControlError("Sai vendor.")
        for unit in ("awccd.service", "i8kmon.service"):
            if self.command("/usr/bin/systemctl", "is-active", unit).stdout.strip() != "inactive":
                raise FanControlError(f"Controller cạnh tranh: {unit}.")
        if self.fence.exists():
            raise FanControlError("Watchdog đã fence phiên.")

    def snapshot(self):
        started = time.monotonic()
        state = self.backend.snapshot()
        # HardwareBackend timestamps at completion; do not mistake a slow
        # multi-provider read for a fresh, coherent safety sample.
        if time.monotonic() - started > 3:
            raise FanControlError("Snapshot phần cứng mất >3 giây; không dùng để ghi quạt.")
        return state

    def ac(self):
        return any(p.read_text().strip() == "1" for p in Path("/sys/class/power_supply").glob("AC*/online"))

    def daemon(self):
        result = self.command("/usr/bin/powerprofilesctl", "get")
        if result.returncode or result.stdout.strip() not in {"balanced", "performance", "power-saver"}:
            raise FanControlError("Không đọc được PPD.")
        return result.stdout.strip()

    def publish_deadline(self, path, deadline):
        temporary = path.with_name(path.name + ".next")
        temporary.write_text(str(deadline))
        os.replace(temporary, path)

    def arm_recovery(self, original):
        if self.guardian is not None or original not in {"balanced", "performance"}:
            raise FanControlError("Guardian/đường khôi phục không hợp lệ.")
        self.original = original
        self.publish_deadline(self.startup_deadline, time.monotonic() + 150)
        parent = os.getpid()
        self.guardian = os.fork()
        if self.guardian == 0:
            self._watchdog(parent)
        self.audit("guardian-armed", pid=self.guardian, original=original)

    def _watchdog(self, parent):
        os.setsid()
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        deadline = time.monotonic() + 150
        while not self.verified.exists():
            for path in (self.startup_deadline, self.custom_deadline, self.heartbeat_deadline):
                if path == self.heartbeat_deadline and self.recovering.exists():
                    continue  # Normal recovery may take >5s; hard deadline/parent death still apply.
                if path.exists():
                    try:
                        value = float(path.read_text())
                        # NaN/inf or torn state must trigger recovery, not disable it.
                        if not 0 < value < float("inf"):
                            raise ValueError("Invalid deadline")
                        if path in (self.startup_deadline, self.custom_deadline):
                            deadline = min(deadline, value)
                        elif time.monotonic() >= value:
                            deadline = 0
                    except (OSError, ValueError):
                        deadline = 0
            if time.monotonic() >= deadline or os.getppid() != parent:
                self.fence.touch(mode=0o600)
                self.audit("watchdog-fired", parent_alive=os.getppid() == parent)
                try:
                    os.kill(parent, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    self.recover()
                finally:
                    os._exit(0)
            time.sleep(.1)
        os._exit(0)

    def heartbeat(self):
        with self.locked("mutation.lock"):
            self._require_active_lease()
            self.publish_deadline(self.heartbeat_deadline, time.monotonic() + HEARTBEAT_SECONDS)

    def _require_active_lease(self, required_seconds=0):
        if self.guardian is None or self.fence.exists():
            raise FanControlError("Không có guardian hoặc write đã bị fence.")
        for path in (self.startup_deadline, self.custom_deadline, self.heartbeat_deadline):
            if path != self.startup_deadline and not path.exists():
                continue
            try:
                deadline = float(path.read_text())
            except (OSError, ValueError) as exc:
                raise FanControlError("Deadline không hợp lệ.") from exc
            if not time.monotonic() + required_seconds < deadline < float("inf"):
                raise FanControlError("Phiên đã hết hạn; cần khôi phục.")

    def _write(self, path, value, *, recovery=False):
        with self.locked("mutation.lock"):
            if not recovery:
                self._require_active_lease()
                if path != self.profile and self.profile.read_text().strip() != "custom":
                    raise FanControlError("Chỉ ghi boost trong Custom.")
            elif path != self.profile and value == 0 and self.profile.read_text().strip() != self.original:
                raise FanControlError("Không restore boost 0 vào profile chưa xác minh.")
            started = time.monotonic()
            self.audit("write-start", node=path.name, value=value, recovery=recovery)
            try:
                path.write_text(str(value) + "\n")
            finally:
                self.audit("write-finished", node=path.name, value=value, recovery=recovery,
                           elapsed=time.monotonic() - started)

    def set_boost(self, channel, raw):
        if type(channel) is not int or channel not in CHANNELS or not valid_raw(raw):
            raise FanControlError("Ngoài allow-list AWCC.")
        self._write(self.hwmon / f"fan{channel}_boost", raw)

    def _set_daemon(self, mode, *, recovery=False):
        with self.locked("mutation.lock"):
            if not recovery:
                self._require_active_lease(20)
            try:
                result = self.command("/usr/bin/powerprofilesctl", "set", mode, timeout=20)
                self.audit("ppd-request", mode=mode, returncode=result.returncode, recovery=recovery)
            except subprocess.TimeoutExpired:
                self.audit("ppd-timeout", mode=mode, recovery=recovery)
        # A successful exit is NOT proof; verify actual PPD + physical profile.

    def _verify_pair(self, mode, profile):
        good = True
        for delay in (0, .4, .6, 1):
            time.sleep(delay)
            state, daemon = self.snapshot(), self.daemon()
            self.audit("profile-sample", profile=state.profile.current, daemon=daemon)
            good = good and state.profile.current == profile and daemon == mode
        return good

    def set_cooling(self):
        self._set_daemon("power-saver")
        if not self._verify_pair("power-saver", "low-power"):
            raise FanControlError("Không xác minh được Low Power.")

    def enter_custom(self):
        self.publish_deadline(self.custom_deadline, time.monotonic() + HARD_SECONDS)
        self._write(self.profile, "custom")

    @staticmethod
    def sleep(seconds):
        time.sleep(seconds)

    def recover(self):
        with self.locked("recovery.lock"):
            if self.verified.exists():
                return True
            self.fence.touch(mode=0o600)
            self.recovering.touch(mode=0o600)
            self.audit("recovery-start", original=self.original)
            try:
                self._set_daemon("balanced", recovery=True)
                if not self._verify_pair("balanced", "balanced"):
                    self._write(self.profile, "balanced", recovery=True)
                    if not self._verify_pair("balanced", "balanced"):
                        raise FanControlError("Balanced bridge thất bại.")
                if self.original == "performance":
                    self._set_daemon("performance", recovery=True)
                    if not self._verify_pair("performance", "performance"):
                        raise FanControlError("Performance restore thất bại.")
                elif self.original != "balanced":
                    raise FanControlError("Không có original profile.")
                # Baseline boost must be zero at start; never write zeros into Custom.
                for channel in CHANNELS:
                    self._write(self.hwmon / f"fan{channel}_boost", 0, recovery=True)
                good = True
                for delay in (0, .4, .6, 1):
                    time.sleep(delay)
                    state, daemon = self.snapshot(), self.daemon()
                    boosts = {f.channel: f.boost for f in state.awcc_fans}
                    good = good and state.profile.current == self.original and daemon == self.original
                    good = good and boosts == dict.fromkeys(CHANNELS, 0)
                    good = good and len(state.fans) == 4 and all(f.pwm_enable == 2 for f in state.fans)
                    self.audit("restore-sample", profile=state.profile.current, daemon=daemon,
                               boosts=boosts, rpm={f.channel: f.rpm for f in state.awcc_fans})
                if not good or any(f.rpm is None or f.rpm <= 0 for f in state.awcc_fans):
                    raise FanControlError("Không xác minh đầy đủ profile/boost/BIOS auto/quạt quay.")
                self.verified.touch(mode=0o600)
                self.audit("restore-complete", ok=True)
                return True
            except Exception as exc:
                self.audit("restore-complete", ok=False, error=str(exc))
                try:
                    still_custom = self.profile.read_text().strip() == "custom"
                except OSError:
                    still_custom = False
                if still_custom:
                    for channel in CHANNELS:
                        try:
                            self._write(self.hwmon / f"fan{channel}_boost", 100, recovery=True)
                        except OSError:
                            pass
                return False

    def finish(self):
        # A failed parent recovery requests an independent second attempt.
        if self.guardian is not None:
            if not self.verified.exists():
                self.publish_deadline(self.custom_deadline, 0)
            os.waitpid(self.guardian, 0)
        os.close(self.audit_fd)
        return self.verified.exists()

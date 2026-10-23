from __future__ import annotations

import json
import os
import stat
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from gi.repository import GLib

from .profile_control import SAFE_PROFILES
from .helper_integrity import helper_payload_reason


HELPER_PATH = Path("/usr/libexec/awcc-profile-helper")
HELPER_TIMEOUT = 75


@dataclass(frozen=True, slots=True)
class ClientResult:
    ok: bool
    message: str
    final_profile: str | None = None


class ProfileClient:
    def __init__(self, helper_path: Path = HELPER_PATH) -> None:
        self.helper_path = helper_path
        self.busy = False

    @property
    def available(self) -> bool:
        try:
            metadata = self.helper_path.stat()
        except OSError:
            return False
        unsafe_write_bits = stat.S_IWGRP | stat.S_IWOTH
        return (
            self.helper_path.is_file()
            and metadata.st_uid == 0
            and not metadata.st_mode & unsafe_write_bits
            and os.access(self.helper_path, os.X_OK)
            and helper_payload_reason() is None
        )

    @property
    def unavailable_reason(self) -> str:
        return helper_payload_reason() or "Privileged helper chưa khả dụng hoặc quyền file không hợp lệ."

    def set_profile(
        self,
        profile: str,
        callback: Callable[[ClientResult], None],
    ) -> bool:
        if self.busy:
            return False
        if profile not in SAFE_PROFILES:
            callback(ClientResult(False, "Profile không được ứng dụng cho phép."))
            return False
        if not self.available:
            callback(ClientResult(False, self.unavailable_reason))
            return False

        self.busy = True

        def worker() -> None:
            try:
                completed = subprocess.run(
                    ["pkexec", str(self.helper_path), "set-profile", profile],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=HELPER_TIMEOUT,
                )
                result = self._parse_result(completed)
            except subprocess.TimeoutExpired:
                result = ClientResult(False, "Helper quá thời gian chờ; hãy kiểm tra profile hiện tại.")
            except OSError as exc:
                result = ClientResult(False, f"Không chạy được helper: {exc}")
            GLib.idle_add(self._finish, callback, result)

        threading.Thread(target=worker, name="awcc-profile-change", daemon=True).start()
        return True

    @staticmethod
    def _parse_result(completed: subprocess.CompletedProcess[str]) -> ClientResult:
        output = completed.stdout.strip()
        try:
            payload = json.loads(output)
            if not isinstance(payload, dict):
                raise TypeError("Helper payload must be an object")
        except (json.JSONDecodeError, TypeError):
            if completed.returncode in {126, 127}:
                return ClientResult(False, "Yêu cầu xác thực đã bị hủy.")
            detail = completed.stderr.strip() or output or f"exit {completed.returncode}"
            return ClientResult(False, f"Helper trả kết quả không hợp lệ: {detail}")
        return ClientResult(
            completed.returncode == 0 and payload.get("ok") is True,
            "Profile đã được đổi và giữ ổn định."
            if completed.returncode == 0 and payload.get("ok") is True
            else str(payload.get("error", "Không đổi được profile.")),
            payload.get("final"),
        )

    def _finish(self, callback: Callable[[ClientResult], None], result: ClientResult) -> bool:
        self.busy = False
        callback(result)
        return GLib.SOURCE_REMOVE

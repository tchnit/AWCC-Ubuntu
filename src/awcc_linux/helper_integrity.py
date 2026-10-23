"""Read-only compatibility check of the root-owned helper payload."""
from __future__ import annotations

import hashlib
from pathlib import Path
import stat


HELPER_MODULES = (
    "__init__.py", "discovery.py", "profile_policy.py", "profile_control.py",
    "profile_helper.py", "profile_recovery.py",
    "backend.py", "models.py",
)
HELPER_LIBRARY = Path("/usr/lib/alienware-control-center/awcc_linux")


def helper_payload_reason(installed: Path = HELPER_LIBRARY) -> str | None:
    local = Path(__file__).resolve().parent
    try:
        for directory in (installed, installed.parent):
            metadata = directory.stat()
            if metadata.st_uid != 0 or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                return "Thư mục helper không được bảo vệ bằng quyền root."
        for name in HELPER_MODULES:
            path = installed / name
            metadata = path.stat()
            if metadata.st_uid != 0 or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                return "Mã helper không được bảo vệ bằng quyền root."
            if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256((local / name).read_bytes()).digest():
                return "Helper hệ thống cần cập nhật để khớp ứng dụng."
    except OSError:
        return "Helper hệ thống chưa đầy đủ; cần cài bản cập nhật."
    return None

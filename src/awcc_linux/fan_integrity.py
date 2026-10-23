"""Separate fan deployment gate. Installing a candidate never enables writes in UI."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat

from .fan_policy import BIOS, DRIVER, KERNEL, MODEL, PROTOCOL
from .helper_integrity import HELPER_LIBRARY, HELPER_MODULES, helper_payload_reason

FAN_MODULES = ("fan_policy.py", "fan_session.py", "fan_hardware.py", "fan_helper.py", "fan_integrity.py")
FAN_HELPER = Path("/usr/libexec/awcc-fan-helper")
DEPLOYMENT = HELPER_LIBRARY.parent / "fan-control-verified.json"


def protected(path: Path, *, directory=False) -> bool:
    meta = path.lstat()
    correct = stat.S_ISDIR(meta.st_mode) if directory else stat.S_ISREG(meta.st_mode)
    return correct and meta.st_uid == 0 and not meta.st_mode & 0o022


def payload_digest(directory: Path = HELPER_LIBRARY) -> str:
    digest = hashlib.sha256()
    for name in (*HELPER_MODULES, *FAN_MODULES):
        digest.update(name.encode() + b"\0" + (directory / name).read_bytes())
    return digest.hexdigest()


def fan_candidate_reason() -> str | None:
    common = helper_payload_reason()
    if common:
        return common
    try:
        if not protected(FAN_HELPER) or not FAN_HELPER.stat().st_mode & 0o111:
            return "Fan helper không được root bảo vệ hoặc không thực thi được."
        if not protected(FAN_HELPER.parent, directory=True):
            return "Thư mục fan helper không an toàn."
        local = Path(__file__).resolve().parent
        for name in FAN_MODULES:
            installed = HELPER_LIBRARY / name
            if not protected(installed) or installed.read_bytes() != (local / name).read_bytes():
                return "Fan helper cần cập nhật; payload không khớp hoặc không an toàn."
    except OSError:
        return "Fan helper mới chưa được cài; thanh kéo chỉ xem trước."
    return None


def fan_deployment_reason() -> str | None:
    reason = fan_candidate_reason()
    if reason:
        return reason
    try:
        if not protected(DEPLOYMENT) or not protected(DEPLOYMENT.parent, directory=True):
            return "Chứng nhận fan helper không được root bảo vệ."
        data = json.loads(DEPLOYMENT.read_text())
        expected = {"protocol": PROTOCOL, "model": MODEL, "bios": BIOS,
                    "kernel": KERNEL, "driver": DRIVER, "payload_sha256": payload_digest(),
                    "status": "e2e-verified"}
        if data != expected:
            return "Fan helper chưa được kiểm chứng end-to-end đúng payload/hardware này."
    except (OSError, ValueError, TypeError):
        return "Chưa kiểm chứng end-to-end fan helper mới; không mở hardware write."
    return None

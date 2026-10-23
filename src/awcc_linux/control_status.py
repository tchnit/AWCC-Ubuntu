"""Presentation states only: this module never grants hardware capabilities."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ControlStatus:
    kind: str
    label: str
    detail: str
    enabled: bool
    selected: bool = False


def control_status(
    *,
    selected: bool = False,
    busy: bool = False,
    block_reason: str | None = None,
    available: bool = True,
    preview: bool = False,
    detail: str = "",
    selected_label: str = "Đang chọn",
) -> ControlStatus:
    if busy:
        return ControlStatus(
            "busy", "Đang xử lý", "Đợi yêu cầu chuyển profile hiện tại hoàn tất.", False, selected
        )
    if selected:
        return ControlStatus(
            "selected", selected_label,
            "Chỉ xem trước; chưa áp dụng tốc độ quạt."
            if preview else "Bấm lại không gửi lệnh phần cứng.", True, True,
        )
    if block_reason:
        return ControlStatus("blocked", "Bị khóa", block_reason, False)
    if not available:
        return ControlStatus(
            "unavailable", "Chưa sẵn sàng",
            "Không có power-profiles-daemon hoặc privileged helper hợp lệ.", False,
        )
    if preview:
        return ControlStatus(
            "preview", "Chỉ xem trước", "Chọn cấu hình; không thay đổi tốc độ quạt.", True
        )
    return ControlStatus("ready", "Có thể chọn", detail, True)

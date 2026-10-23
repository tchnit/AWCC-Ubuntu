from __future__ import annotations

import unittest

from awcc_linux.control_status import control_status


class ControlStatusTests(unittest.TestCase):
    def test_selected_is_enabled_and_not_greyed_as_blocked(self) -> None:
        status = control_status(selected=True, available=False)
        self.assertTrue(status.enabled)
        self.assertTrue(status.selected)
        self.assertEqual(status.kind, "selected")
        self.assertIn("không gửi lệnh", status.detail)

    def test_current_profile_has_distinct_label(self) -> None:
        self.assertEqual(
            control_status(selected=True, selected_label="Đang dùng").label, "Đang dùng"
        )

    def test_blocked_keeps_reason_visible(self) -> None:
        status = control_status(block_reason="Firmware rollback")
        self.assertFalse(status.enabled)
        self.assertEqual(status.kind, "blocked")
        self.assertEqual(status.detail, "Firmware rollback")

    def test_unavailable_is_not_a_hardware_rejection(self) -> None:
        status = control_status(available=False)
        self.assertFalse(status.enabled)
        self.assertEqual(status.kind, "unavailable")
        self.assertIn("helper", status.detail)

    def test_preview_is_clickable_but_explicitly_not_hardware_control(self) -> None:
        status = control_status(preview=True)
        self.assertTrue(status.enabled)
        self.assertEqual(status.label, "Chỉ xem trước")
        self.assertIn("không thay đổi tốc độ quạt", status.detail)

    def test_selected_preview_stays_marked_as_preview(self) -> None:
        status = control_status(
            selected=True, preview=True, selected_label="Đang chọn · Xem trước"
        )
        self.assertTrue(status.enabled)
        self.assertIn("Xem trước", status.label)
        self.assertIn("chưa áp dụng", status.detail)

    def test_busy_disables_even_selected_without_claiming_hardware_failure(self) -> None:
        status = control_status(busy=True, selected=True)
        self.assertFalse(status.enabled)
        self.assertTrue(status.selected)
        self.assertEqual(status.kind, "busy")

    def test_ready_keeps_action_explanation(self) -> None:
        status = control_status(detail="Verify read-back")
        self.assertTrue(status.enabled)
        self.assertEqual(status.detail, "Verify read-back")

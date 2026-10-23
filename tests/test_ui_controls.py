"""GTK integration: fake transports, read-only backend, temporary settings.

Skipped if no display is available. Never invoke a real profile client write.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

from awcc_linux.backend import HardwareBackend
from awcc_linux.models import Temperature
from awcc_linux.resource_telemetry import ResourceMetrics
from awcc_linux.power_profiles import PowerProfilesState
from awcc_linux.presets import PRESETS_BY_KEY
from awcc_linux.settings import SettingsStore
from awcc_linux.ui import Dashboard, scroll_restore_target
from awcc_linux.fan_client import FanClientState

Gtk.init_check()


class ScrollRestoreTargetTests(unittest.TestCase):
    def test_middle_position_is_preserved_and_clamped(self) -> None:
        self.assertEqual(scroll_restore_target(240, 1000, 300, False), 240)
        self.assertEqual(scroll_restore_target(900, 1000, 300, False), 700)

    def test_bottom_position_stays_at_new_bottom(self) -> None:
        self.assertEqual(scroll_restore_target(700, 1200, 300, True), 900)


def descendants(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from descendants(child)
        child = child.get_next_sibling()


def cards(box):
    return [child.get_child() for child in descendants(box) if isinstance(child, Gtk.FlowBoxChild)]


@unittest.skipUnless(Gdk.Display.get_default() is not None, "GTK display unavailable")
class DashboardControlTests(unittest.TestCase):
    def setUp(self) -> None:
        Adw.init()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.profile = Mock(available=True, busy=False)
        self.power = Mock(busy=False)
        self.power.state = PowerProfilesState(
            True, "balanced", ("power-saver", "balanced", "performance")
        )
        self.power.refresh.return_value = self.power.state
        state = HardwareBackend().snapshot()
        self.state = replace(
            state, model="Alienware x17 R1", bios_version="1.27.0",
            profile=replace(state.profile, current="balanced", choices=(
                "low-power", "quiet", "balanced", "balanced-performance", "performance", "custom"
            )),
        )
        self.backend = Mock()
        self.backend.snapshot.return_value = self.state
        self.notify = Mock()
        self.resources = Mock()
        self.resources.read.return_value = ResourceMetrics(2500, 15, 1200, 35, 8 * 1024 ** 3, 16 * 1024 ** 3)
        class InlinePoller:
            def __init__(poller, reader, dispatch):
                poller.reader = reader
            def request(poller, success, failure):
                success(poller.reader())
                return True
            def close(poller):
                pass
        with patch("awcc_linux.ui.ProfileClient", return_value=self.profile), patch(
            "awcc_linux.ui.PowerProfilesClient", return_value=self.power
        ), patch("awcc_linux.ui.SnapshotPoller", InlinePoller):
            self.dashboard = Dashboard(
                self.backend, self.notify, SettingsStore(Path(self.temp.name) / "settings.json"), self.resources
            )
        self.addCleanup(self.dashboard.close)

    def test_refresh_preserves_control_and_sensor_widgets(self):
        card = self.profile_card("Cân bằng")
        sensor_card = next(iter(self.dashboard.sensor_cards.values()))
        self.dashboard.refresh()
        self.assertIs(self.profile_card("Cân bằng"), card)
        self.assertIs(next(iter(self.dashboard.sensor_cards.values())), sensor_card)

    def fake_fan_client(self, **state_values):
        client = Mock(available=True, unavailable_reason=None)
        client.state = FanClientState(**state_values)
        self.dashboard.fan_client = client
        return client

    def test_fan_sliders_are_present_but_disabled_without_custom_lease(self):
        self.assertEqual(set(self.dashboard.fan_sliders), {1,2,3,4})
        for channel, slider in self.dashboard.fan_sliders.items():
            self.assertFalse(slider.get_sensitive())
            self.assertFalse(self.dashboard.fan_apply[channel].get_sensitive())
        self.assertFalse(self.dashboard.fan_start.get_sensitive())
        self.assertIn("raw 0–255", self.dashboard.fan_session_label.get_text())
        self.assert_no_hardware_requests()

    def test_fan_slider_only_selects_apply_explicitly_sends_during_custom(self):
        client = self.fake_fan_client(running=True,ready=True)
        self.backend.snapshot.return_value = replace(self.state,profile=replace(self.state.profile,current="custom"))
        self.dashboard.refresh()
        slider = self.dashboard.fan_sliders[3]
        self.assertTrue(slider.get_sensitive())
        slider.set_value(70)
        self.assertEqual(slider.get_value(),70)
        client.set_boost.assert_not_called()
        self.dashboard.fan_apply[3].emit("clicked")
        client.set_boost.assert_called_once_with(3,70)
        self.assert_no_hardware_requests()

    def test_fan_slider_spans_full_raw_range_with_integer_step(self):
        client = self.fake_fan_client(running=True,ready=True)
        self.backend.snapshot.return_value = replace(self.state,profile=replace(self.state.profile,current="custom"))
        self.dashboard.refresh()
        for channel,slider in self.dashboard.fan_sliders.items():
            adjustment = slider.get_adjustment()
            self.assertEqual((adjustment.get_lower(),adjustment.get_upper(),adjustment.get_step_increment()),(0,255,1))
            for value in (0,1,70,128,254,255):
                slider.set_value(value)
                self.assertEqual(self.dashboard.fan_desired[channel],value)
        client.set_boost.assert_not_called()

    def test_fan_callbacks_cannot_bypass_custom_or_deployment_gate(self):
        client = self.fake_fan_client(running=True,ready=True)
        self.dashboard._apply_fan(Gtk.Button(),1)
        client.set_boost.assert_not_called()
        self.backend.snapshot.return_value = replace(self.state,profile=replace(self.state.profile,current="custom"))
        self.dashboard.refresh()
        client.available = False
        client.unavailable_reason = "chưa kiểm chứng helper"
        self.dashboard._apply_fan(Gtk.Button(),1)
        client.set_boost.assert_not_called()

    def test_active_fan_session_blocks_all_profile_mutations(self):
        self.fake_fan_client(running=True,ready=True)
        self.dashboard.refresh()
        self.assertFalse(self.button(self.profile_card("Hiệu năng")).get_sensitive())
        self.dashboard._request_profile(Gtk.Button(),"performance")
        self.assertFalse(self.dashboard._set_profile("performance",Mock()))
        self.assert_no_hardware_requests()

    def test_telemetry_refresh_keeps_slider_object_and_pending_selection(self):
        self.fake_fan_client(running=True,ready=True)
        self.backend.snapshot.return_value = replace(self.state,profile=replace(self.state.profile,current="custom"))
        self.dashboard.refresh()
        slider = self.dashboard.fan_sliders[4]
        slider.set_value(64)
        self.dashboard.refresh()
        self.assertIs(self.dashboard.fan_sliders[4],slider)
        self.assertEqual(slider.get_value(),64)

    def test_start_button_requires_custom_and_no_pending_profile(self):
        client = self.fake_fan_client()
        client.start.return_value = True
        self.dashboard._start_fans(Gtk.Button())
        client.start.assert_not_called()
        self.backend.snapshot.return_value = replace(self.state,profile=replace(self.state.profile,current="custom"))
        self.dashboard.refresh()
        self.assertTrue(self.dashboard.fan_start.get_sensitive())
        self.dashboard.fan_start.emit("clicked")
        client.start.assert_called_once()

    def test_closing_dashboard_requests_fan_recovery_without_waiting_on_gtk(self):
        client = self.fake_fan_client(running=True,ready=True)
        self.dashboard.close()
        client.close.assert_called_once()

    def test_all_sensors_are_metric_cards_without_channel_list(self):
        sensors = (
            Temperature(1, "CPU", 45, "AWCC WMI"),
            Temperature(1, "GPU", 39, "NVIDIA NVML"),
            Temperature(3, "SODIMM", 37, "dell_smm"),
            Temperature(6, "Other", 36, "dell_smm"),
        )
        self.backend.snapshot.return_value = replace(self.state, temperatures=sensors)
        self.dashboard.refresh()
        self.assertFalse(hasattr(self.dashboard, "temp_list"))
        self.assertEqual(set(self.dashboard.sensor_cards), {"cpu", "gpu", "sodimm", "other"})
        self.assertEqual(cards(self.dashboard.metrics)[:4], [self.dashboard.sensor_cards[key] for key in ("cpu", "gpu", "sodimm", "other")])
        for sensor in sensors:
            card = self.dashboard.sensor_cards[sensor.label.casefold()]
            self.assertEqual(card.value_label.get_text(), f"{sensor.celsius:.0f} °C")
            self.assertIn(sensor.source, card.subtitle_label.get_text())
            self.assertNotIn("temp", card.subtitle_label.get_text())
        self.assert_no_hardware_requests()

    def test_sensor_topology_and_values_update_without_rebuilding_existing_cards(self):
        self.backend.snapshot.return_value = replace(self.state, temperatures=(Temperature(1,"CPU",45,"AWCC WMI"),Temperature(1,"GPU",39,"NVIDIA NVML")))
        self.dashboard.refresh()
        cpu = self.dashboard.sensor_cards["cpu"]
        self.backend.snapshot.return_value = replace(self.state, temperatures=(Temperature(1,"CPU",48,"AWCC WMI"),Temperature(3,"SODIMM",37,"dell_smm")))
        self.dashboard.refresh()
        self.assertIs(self.dashboard.sensor_cards["cpu"], cpu)
        self.assertEqual(cpu.value_label.get_text(), "48 °C")
        self.assertEqual(self.dashboard.sensor_cards["gpu"].value_label.get_text(), "—")
        self.assertIn("Không có dữ liệu", self.dashboard.sensor_cards["gpu"].subtitle_label.get_text())
        self.backend.snapshot.return_value = replace(self.state, temperatures=(Temperature(1,"CPU",48,"AWCC WMI"),))
        self.dashboard.refresh()
        self.assertNotIn("sodimm", self.dashboard.sensor_cards)
        self.assertEqual(cards(self.dashboard.metrics)[-2:], [self.dashboard.fans_card, self.dashboard.profile_card])
        self.assert_no_hardware_requests()

    def test_refresh_does_not_read_hardware_on_gtk_thread(self):
        self.dashboard.poller = Mock()
        self.backend.snapshot.reset_mock()
        self.resources.read.reset_mock()
        self.dashboard.refresh()
        self.backend.snapshot.assert_not_called()
        self.resources.read.assert_not_called()
        self.dashboard.poller.request.assert_called_once()

    def test_three_resource_cards_display_clock_usage_and_ram(self):
        self.assertEqual(self.dashboard.cpu_usage_card.value_label.get_text(), "2.50 GHz / 15 %")
        self.assertEqual(self.dashboard.gpu_usage_card.value_label.get_text(), "1200 MHz / 35 %")
        self.assertEqual(self.dashboard.ram_card.value_label.get_text(), "8.0 / 16.0 GiB")
        self.assertIn("50 %", self.dashboard.ram_card.subtitle_label.get_text())
        self.assertIn("cache", self.dashboard.ram_card.subtitle_label.get_text())
        self.assert_no_hardware_requests()

    def test_resource_refresh_keeps_cards_and_missing_data_is_not_zero(self):
        card = self.dashboard.cpu_usage_card
        self.resources.read.return_value = ResourceMetrics(cpu_mhz=2800)
        self.dashboard.refresh()
        self.assertIs(self.dashboard.cpu_usage_card, card)
        self.assertEqual(card.value_label.get_text(), "2.80 GHz / —")
        self.assertEqual(self.dashboard.gpu_usage_card.value_label.get_text(), "— / —")
        self.assertEqual(self.dashboard.ram_card.value_label.get_text(), "— / —")
        self.assert_no_hardware_requests()

    def test_real_poller_keeps_gtk_responsive_while_reader_blocks(self):
        started, release = threading.Event(), threading.Event()
        def reader():
            started.set()
            release.wait(2)
            return self.state
        self.backend.snapshot.side_effect = reader
        with patch("awcc_linux.ui.ProfileClient", return_value=self.profile), patch("awcc_linux.ui.PowerProfilesClient", return_value=self.power):
            dashboard = Dashboard(self.backend, self.notify, SettingsStore(Path(self.temp.name) / "async-settings.json"), self.resources)
        try:
            self.assertTrue(started.wait(2))
            self.assertIsNone(dashboard.last_snapshot)
            idle_ran = []
            GLib.idle_add(lambda: idle_ran.append(True) and False)
            context = GLib.MainContext.default()
            for _ in range(50):
                if not context.pending():
                    break
                context.iteration(False)
            self.assertTrue(idle_ran)
        finally:
            dashboard.close()
            release.set()

    def profile_card(self, title):
        for card in cards(self.dashboard.profile_box):
            labels = [w.get_label() for w in descendants(card) if isinstance(w, Gtk.Label)]
            if title in labels:
                return card
        self.fail(f"No profile card {title}")

    def preset_card(self, title):
        for card in cards(self.dashboard.preset_box):
            labels = [w.get_label() for w in descendants(card) if isinstance(w, Gtk.Label)]
            if title in labels:
                return card
        self.fail(f"No preset card {title}")

    @staticmethod
    def button(card):
        return next(w for w in descendants(card) if isinstance(w, Gtk.ToggleButton))

    def assert_no_hardware_requests(self):
        self.profile.set_profile.assert_not_called()
        self.power.set_platform_profile.assert_not_called()

    def test_current_profile_is_highlighted_and_clickable_without_write(self) -> None:
        card = self.profile_card("Cân bằng")
        button = self.button(card)
        self.assertTrue(card.has_css_class("control-selected"))
        self.assertTrue(button.get_sensitive())
        self.assertTrue(button.get_active())
        button.emit("clicked")
        self.assert_no_hardware_requests()
        self.assertTrue(self.button(self.profile_card("Cân bằng")).get_active())

    def test_failed_profile_shows_readable_reason_outside_disabled_button(self) -> None:
        self.backend.snapshot.return_value = replace(self.state,bios_version="1.28.0")
        self.dashboard.refresh()
        card = self.profile_card("Custom (thermal)")
        self.assertTrue(card.get_sensitive())
        self.assertFalse(self.button(card).get_sensitive())
        labels = [w.get_label() for w in descendants(card) if isinstance(w, Gtk.Label)]
        self.assertIn("Bị khóa", labels)
        self.assertTrue(any("chưa được kiểm chứng" in text for text in labels))

    def test_verified_balanced_performance_uses_helper(self) -> None:
        card = self.profile_card("Cân bằng+")
        self.assertTrue(self.button(card).get_sensitive())
        self.button(card).emit("clicked")
        self.assertEqual(self.profile.set_profile.call_args.args[0],"balanced-performance")
        self.power.set_platform_profile.assert_not_called()

    def test_low_power_is_enabled_and_uses_ppd(self):
        card=self.profile_card("Tiết kiệm")
        self.assertTrue(self.button(card).get_sensitive())
        self.button(card).emit("clicked")
        self.assertEqual(self.power.set_platform_profile.call_args.args[0],"low-power")
        self.profile.set_profile.assert_not_called()

    def test_custom_is_enabled_as_thermal_not_manual_fan(self):
        card=self.profile_card("Custom (thermal)")
        self.assertTrue(self.button(card).get_sensitive())
        self.assertIn("không phải fan curve", self.button(card).get_tooltip_text())
        self.button(card).emit("clicked")
        self.assertEqual(self.profile.set_profile.call_args.args[0],"custom")

    def test_daemon_managed_performance_uses_ppd(self) -> None:
        card = self.profile_card("Hiệu năng")
        button = self.button(card)
        self.assertTrue(button.get_sensitive())
        self.assertIn("power-profiles-daemon", button.get_tooltip_text())
        button.emit("clicked")
        self.assertEqual(self.power.set_platform_profile.call_args.args[0], "performance")
        self.profile.set_profile.assert_not_called()

    def test_daemon_unmanaged_profile_uses_helper(self) -> None:
        card = self.profile_card("Yên tĩnh")
        self.assertTrue(self.button(card).get_sensitive())
        self.assertIn("privileged helper", self.button(card).get_tooltip_text())
        self.button(card).emit("clicked")
        self.profile.set_profile.assert_called_once()
        self.power.set_platform_profile.assert_not_called()

    def test_quiet_preset_is_a_visible_hardware_profile_action(self) -> None:
        card = self.preset_card("Yên tĩnh")
        button = self.button(card)
        self.assertTrue(button.get_sensitive())
        self.assertIn("helper", button.get_tooltip_text())
        button.emit("clicked")
        self.assertEqual(self.profile.set_profile.call_args.args[0], "quiet")
        self.power.set_platform_profile.assert_not_called()

    def test_daemon_unmanaged_profile_without_helper_is_unavailable(self) -> None:
        self.profile.available = False
        self.dashboard.refresh()
        card = self.profile_card("Cân bằng+")
        self.assertFalse(self.button(card).get_sensitive())
        self.assertIn("helper", self.button(card).get_tooltip_text())

    def test_external_awccd_blocks_new_profile_writes(self) -> None:
        self.backend.snapshot.return_value = replace(
            self.state,
            capabilities=replace(
                self.state.capabilities, external_awccd_controller=True
            ),
        )
        self.dashboard.refresh()

        card = self.profile_card("Yên tĩnh")
        self.assertFalse(self.button(card).get_sensitive())
        labels = [w.get_label() for w in descendants(card) if isinstance(w, Gtk.Label)]
        self.assertTrue(any("awccd" in text for text in labels))
        self.assertIn("Xung đột controller", self.dashboard.banner.get_title())

    def test_direct_callback_cannot_bypass_hardware_policy(self) -> None:
        self.dashboard._request_profile(Gtk.Button(), "invalid-profile")
        self.assert_no_hardware_requests()

    def test_phase_5b_fan_preview_is_not_rendered(self) -> None:
        labels = [
            widget.get_label()
            for widget in descendants(self.dashboard)
            if isinstance(widget, Gtk.Label)
        ]
        self.assertNotIn("Fan modes · Giai đoạn 5B", labels)
        self.assertNotIn("Custom curve", labels)
        self.assertFalse(hasattr(self.dashboard, "mode_box"))

    def test_sensors_and_fans_are_before_profile_controls(self) -> None:
        titles = [
            widget.get_label()
            for widget in descendants(self.dashboard)
            if isinstance(widget, Gtk.Label)
        ]

        self.assertNotIn("Cảm biến", titles)
        self.assertNotIn("Kênh cảm biến", titles)
        self.assertLess(titles.index("CPU"), titles.index("Quạt"))
        self.assertLess(titles.index("Quạt"), titles.index("Preset an toàn"))

    def test_busy_is_visible_and_disabled(self) -> None:
        self.power.busy = True
        self.dashboard.refresh()
        card = self.profile_card("Cân bằng")
        self.assertFalse(self.button(card).get_sensitive())
        self.assertIn("Đang xử lý", self.button(card).get_tooltip_text())

    def test_selected_preset_does_not_save_or_write_again(self) -> None:
        with patch.object(self.dashboard.settings_store, "save") as save:
            self.dashboard._request_preset(Gtk.Button(), PRESETS_BY_KEY["auto"])
            save.assert_not_called()
        self.assert_no_hardware_requests()

    def test_missing_transports_has_distinct_reason(self) -> None:
        self.power.state = PowerProfilesState()
        self.power.refresh.return_value = self.power.state
        self.profile.available = False
        self.backend.snapshot.return_value = replace(self.state, bios_version="1.28.0")
        self.dashboard.refresh()
        card = self.profile_card("Hiệu năng")
        self.assertTrue(card.has_css_class("control-unavailable"))
        self.assertFalse(self.button(card).get_sensitive())
        self.assertIn("helper", self.button(card).get_tooltip_text())
        self.dashboard._request_profile(Gtk.Button(), "performance")
        self.assert_no_hardware_requests()

    def test_performance_fallback_is_blocked_on_tested_machine(self) -> None:
        self.power.state = PowerProfilesState()
        self.power.refresh.return_value = self.power.state
        self.dashboard.refresh()
        card = self.profile_card("Hiệu năng")
        self.assertFalse(self.button(card).get_sensitive())
        self.assertIn("fallback privileged helper", self.button(card).get_tooltip_text())

from __future__ import annotations

import gi
import time

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .backend import HardwareBackend
from .control_status import ControlStatus, control_status
from .models import ControlState, SystemSnapshot
from .power_profiles import PowerProfileResult, PowerProfilesClient
from .presets import PRESETS, Preset
from .privileged import ClientResult, ProfileClient
from .profile_control import SAFE_PROFILES
from .profile_policy import profile_block_reason
from .settings import AppSettings, REFRESH_OPTIONS, SettingsStore
from .telemetry import SnapshotPoller
from .resource_telemetry import DashboardSnapshot, ResourceMetrics, ResourceReader
from .fan_client import FanClient


PROFILE_LABELS = {
    "low-power": "Tiết kiệm",
    "quiet": "Yên tĩnh",
    "balanced": "Cân bằng",
    "balanced-performance": "Cân bằng+",
    "performance": "Hiệu năng",
    "custom": "Custom (thermal)",
}


def _status_css(state: ControlState) -> str:
    return "success" if state == ControlState.MANUAL else "warning"


def scroll_restore_target(
    value: float,
    upper: float,
    page_size: float,
    was_at_bottom: bool,
) -> float:
    """Return a valid vertical adjustment after refresh changed its content."""

    maximum = max(upper - page_size, 0.0)
    if was_at_bottom:
        return maximum
    return min(max(value, 0.0), maximum)


class MetricCard(Gtk.Box):
    def __init__(self, title: str, value: str = "—", subtitle: str = "") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.add_css_class("metric-card")
        title_label = Gtk.Label(label=title, xalign=0)
        title_label.add_css_class("caption")
        self.value_label = Gtk.Label(label=value, xalign=0)
        self.value_label.add_css_class("metric-value")
        self.subtitle_label = Gtk.Label(label=subtitle, xalign=0)
        self.subtitle_label.add_css_class("dim-label")
        self.subtitle_label.set_wrap(True)
        self.subtitle_label.set_max_width_chars(26)
        self.append(title_label)
        self.append(self.value_label)
        self.append(self.subtitle_label)

    def update(self, value: str, subtitle: str = "") -> None:
        self.value_label.set_text(value)
        self.subtitle_label.set_text(subtitle)


class Dashboard(Gtk.ScrolledWindow):
    def __init__(
        self,
        backend: HardwareBackend,
        notify,
        settings_store: SettingsStore | None = None,
        resource_reader: ResourceReader | None = None,
    ) -> None:
        super().__init__()
        self.backend = backend
        self.notify = notify
        self.profile_client = ProfileClient()
        self.power_client = PowerProfilesClient()
        self.fan_client = FanClient(self._fan_changed)
        self.fan_sliders: dict = {}
        self.fan_apply: dict = {}
        self.fan_desired: dict = {}
        self._syncing_fan_slider = False
        self.settings_store = settings_store or SettingsStore()
        self.settings = self.settings_store.load()
        self.last_snapshot: SystemSnapshot | None = None
        self.pending_preset: str | None = None
        self.refresh_source_id: int | None = None
        self.scroll_restore_source_id: int | None = None
        self.resource_reader = resource_reader or ResourceReader()
        self.resources = ResourceMetrics()
        self.poller = SnapshotPoller(self._read_snapshot, GLib.idle_add)
        self.preset_cards: dict = {}
        self.profile_cards: dict = {}
        self.fan_rows: dict = {}
        self.sensor_cards: dict[str, MetricCard] = {}
        self.closed = False
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
        content.set_margin_top(24)
        content.set_margin_bottom(32)
        content.set_margin_start(28)
        content.set_margin_end(28)
        self.set_child(content)

        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        title = Gtk.Label(label="Alienware x17 R1", xalign=0)
        title.add_css_class("title-1")
        self.system_label = Gtk.Label(xalign=0)
        self.system_label.add_css_class("dim-label")
        hero.append(title)
        hero.append(self.system_label)
        content.append(hero)

        self.banner = Adw.Banner()
        self.banner.set_title("Đang đọc trạng thái phần cứng…")
        self.banner.set_revealed(True)
        content.append(self.banner)

        self.metrics = Gtk.FlowBox()
        self.metrics.set_selection_mode(Gtk.SelectionMode.NONE)
        self.metrics.set_min_children_per_line(2)
        self.metrics.set_max_children_per_line(4)
        self.metrics.set_column_spacing(12)
        self.metrics.set_row_spacing(12)
        self.fans_card = MetricCard("Quạt đang chạy")
        self.profile_card = MetricCard("Thermal profile")
        self.cpu_usage_card = MetricCard("Xung CPU / % CPU")
        self.gpu_usage_card = MetricCard("Xung GPU / % GPU")
        self.ram_card = MetricCard("RAM")
        for card in (self.cpu_usage_card, self.gpu_usage_card, self.ram_card, self.fans_card, self.profile_card):
            self.metrics.insert(card, -1)
        content.append(self.metrics)

        content.append(
            self._section_title(
                "Quạt",
                "Ưu tiên AWCC alienware_wmi; fan_max chỉ là giá trị tham chiếu firmware",
            )
        )
        self.fan_list = Gtk.ListBox()
        self.fan_list.add_css_class("boxed-list")
        self.fan_list.set_selection_mode(Gtk.SelectionMode.NONE)
        content.append(self.fan_list)

        fan_controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.fan_session_label = Gtk.Label(xalign=0, wrap=True)
        self.fan_session_label.add_css_class("dim-label")
        fan_controls.append(self.fan_session_label)
        fan_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.fan_start = Gtk.Button(label="Bắt đầu phiên Custom · tối đa 60 giây")
        self.fan_start.connect("clicked", self._start_fans)
        self.fan_stop = Gtk.Button(label="Dừng và khôi phục")
        self.fan_stop.connect("clicked", lambda *_: self.fan_client.stop())
        fan_buttons.append(self.fan_start)
        fan_buttons.append(self.fan_stop)
        fan_controls.append(fan_buttons)
        content.append(fan_controls)

        content.append(
            self._section_title(
                "Preset an toàn",
                "Chỉ đổi platform profile; BIOS / EC luôn giữ quyền điều khiển quạt",
            )
        )
        self.preset_box = Gtk.FlowBox()
        self.preset_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.preset_box.set_column_spacing(10)
        self.preset_box.set_row_spacing(10)
        self.preset_box.set_min_children_per_line(1)
        self.preset_box.set_max_children_per_line(3)
        content.append(self.preset_box)

        content.append(self._section_title(
            "Thermal profiles",
            "Đang dùng ≠ bị khóa; mỗi lựa chọn hiển thị lý do ngay bên dưới",
        ))
        self.profile_box = Gtk.FlowBox()
        self.profile_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.profile_box.set_column_spacing(10)
        self.profile_box.set_row_spacing(10)
        self.profile_box.set_max_children_per_line(3)
        content.append(self.profile_box)

        content.append(self._section_title("Manual fan control", "Capability gate an toàn"))
        self.control_group = Adw.PreferencesGroup()
        self.control_row = Adw.ActionRow(title="BIOS / EC đang kiểm soát")
        self.control_row.set_subtitle("Ứng dụng không ghi PWM khi chưa xác minh stable takeover.")
        lock = Gtk.Image.new_from_icon_name("changes-prevent-symbolic")
        self.control_row.add_prefix(lock)
        self.control_group.add(self.control_row)
        self.power_row = Adw.ActionRow(title="Power profiles")
        self.control_group.add(self.power_row)
        content.append(self.control_group)

        content.append(self._section_title("Cài đặt", "Lưu ở user scope, không cần root"))
        settings_group = Adw.PreferencesGroup()
        self.refresh_row = Adw.ComboRow(title="Chu kỳ làm mới")
        self.refresh_row.set_subtitle("Tần suất đọc telemetry; không tạo hardware write")
        self.refresh_row.set_model(
            Gtk.StringList.new([f"{seconds} giây" for seconds in REFRESH_OPTIONS])
        )
        self.refresh_row.set_selected(REFRESH_OPTIONS.index(self.settings.refresh_seconds))
        self.refresh_row.connect("notify::selected", self._refresh_changed)
        settings_group.add(self.refresh_row)
        content.append(settings_group)

        self.refresh()
        self._schedule_refresh()

    @staticmethod
    def _section_title(title: str, subtitle: str) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        heading = Gtk.Label(label=title, xalign=0)
        heading.add_css_class("title-3")
        sub = Gtk.Label(label=subtitle, xalign=0)
        sub.add_css_class("dim-label")
        box.append(heading)
        box.append(sub)
        return box

    @staticmethod
    def _clear(container: Gtk.Widget) -> None:
        child = container.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            container.remove(child)
            child = next_child

    @staticmethod
    def _control_card(
        title: str,
        description: str,
        status: ControlStatus,
        button: Gtk.ToggleButton,
        action: str,
    ) -> Gtk.Box:
        # Only the action is disabled; the reason remains legible/focus-independent.
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.add_css_class("control-card")
        card.add_css_class(f"control-{status.kind}")
        title_label = Gtk.Label(label=title, xalign=0)
        title_label.add_css_class("heading")
        card.append(title_label)
        if description:
            text = Gtk.Label(label=description, xalign=0)
            text.set_wrap(True)
            text.set_max_width_chars(28)
            text.add_css_class("dim-label")
            card.append(text)
        badge = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        icons = {
            "selected": "emblem-ok-symbolic",
            "blocked": "changes-prevent-symbolic",
            "unavailable": "dialog-warning-symbolic",
            "busy": "content-loading-symbolic",
            "preview": "view-reveal-symbolic",
            "ready": "emblem-default-symbolic",
        }
        badge.append(Gtk.Image.new_from_icon_name(icons[status.kind]))
        badge.append(Gtk.Label(label=status.label, xalign=0))
        badge.add_css_class("control-badge")
        card.append(badge)
        reason = Gtk.Label(label=status.detail, xalign=0)
        reason.set_wrap(True)
        reason.set_max_width_chars(28)
        reason.set_vexpand(True)
        reason.set_valign(Gtk.Align.START)
        card.append(reason)
        button.set_active(status.selected)
        button.set_sensitive(status.enabled)
        if status.kind == "busy":
            action_label = "Đang xử lý…"
        elif status.selected:
            action_label = "Đang dùng" if status.label == "Đang dùng" else "Đang chọn"
        else:
            action_label = action if status.enabled else "Không khả dụng"
        button.set_label(action_label)
        if status.selected:
            button.add_css_class("suggested-action")
        button.set_tooltip_text(f"{title}: {status.label}. {status.detail}")
        card.append(button)
        card.status_widgets = (badge.get_first_child(), badge.get_last_child(), reason, button)
        card.status_kind = status.kind
        return card

    @staticmethod
    def _update_control_card(card, title, status, action) -> None:
        icon, badge, reason, button = card.status_widgets
        card.remove_css_class(f"control-{card.status_kind}")
        card.add_css_class(f"control-{status.kind}")
        card.status_kind = status.kind
        icon.set_from_icon_name({
            "selected": "emblem-ok-symbolic", "blocked": "changes-prevent-symbolic",
            "unavailable": "dialog-warning-symbolic", "busy": "content-loading-symbolic",
            "preview": "view-reveal-symbolic", "ready": "emblem-default-symbolic",
        }[status.kind])
        badge.set_text(status.label)
        reason.set_text(status.detail)
        button.set_active(status.selected)
        button.set_sensitive(status.enabled)
        button.set_label("Đang xử lý…" if status.kind == "busy" else status.label if status.selected else action if status.enabled else "Không khả dụng")
        if status.selected:
            button.add_css_class("suggested-action")
        else:
            button.remove_css_class("suggested-action")
        button.set_tooltip_text(f"{title}: {status.label}. {status.detail}")

    @staticmethod
    def _sync_rows(container, cache, entries) -> None:
        keys = {key for key, *_ in entries}
        for key in tuple(cache):
            if key not in keys:
                container.remove(cache.pop(key)[0])
        for key, title, subtitle, text in entries:
            if key not in cache:
                row = Adw.ActionRow()
                value = Gtk.Label()
                value.add_css_class("numeric")
                row.add_suffix(value)
                container.append(row)
                cache[key] = (row, value)
            row, value = cache[key]
            row.set_title(title)
            row.set_subtitle(subtitle)
            value.set_text(text)

    def _sync_sensor_cards(self, state: SystemSnapshot) -> None:
        entries = {
            sensor.label.casefold(): (sensor.label, sensor.celsius, sensor.source)
            for sensor in state.temperatures
        }
        # Missing CPU/GPU stay visible as missing data, never a fabricated value.
        for key in ("cpu", "gpu"):
            if not any(key in label for label in entries):
                entries[key] = (key.upper(), None, "")

        def priority(key: str):
            group = 0 if "cpu" in key else 1 if "gpu" in key else 2 if key == "sodimm" else 3
            return group, key

        for key in tuple(self.sensor_cards):
            if key not in entries:
                card = self.sensor_cards.pop(key)
                self.metrics.remove(card.get_parent())
        for index, key in enumerate(sorted(entries, key=priority)):
            title, temperature, source = entries[key]
            if key not in self.sensor_cards:
                card = MetricCard(title)
                self.metrics.insert(card, index)
                self.sensor_cards[key] = card
            card = self.sensor_cards[key]
            if card.get_parent().get_index() != index:
                self.metrics.remove(card.get_parent())
                self.metrics.insert(card, index)
            description = (
                "Processor" if "cpu" in key else "Graphics" if "gpu" in key
                else "Bộ nhớ RAM" if key == "sodimm" else "Cảm biến phụ" if key == "other"
                else ""
            )
            subtitle = " · ".join(part for part in (description, source) if part)
            card.update(
                f"{temperature:.0f} °C" if temperature is not None else "—",
                subtitle if temperature is not None else "Không có dữ liệu hợp lệ",
            )

    def _profile_status(
        self, state: SystemSnapshot, profile: str | None, selected: bool,
        *, preset: bool = False,
    ) -> ControlStatus:
        power_state = self.power_client.state
        daemon_manages_profile = bool(
            profile and power_state.supports_platform_profile(profile)
        )
        # Selecting the current profile only saves UI settings; it never writes.
        record_only = preset and (profile is None or profile == state.profile.current)
        blocked = None
        if profile and not record_only and state.capabilities.external_awccd_controller:
            blocked = (
                "awccd đang chạy và ép profile/fan boost từ cấu hình riêng; "
                "dừng controller này trước khi ứng dụng gửi profile."
            )
        elif profile:
            blocked = profile_block_reason(
                state.model,
                state.bios_version,
                profile,
                verified_ppd_route=daemon_manages_profile,
            )
        if profile and blocked is None:
            if profile not in SAFE_PROFILES:
                blocked = "Profile chưa được policy cho phép."
        transport_available = (
            daemon_manages_profile or self.profile_client.available
        )
        if record_only:
            detail = "Chỉ lưu lựa chọn; không gửi lệnh phần cứng."
        elif profile and not daemon_manages_profile:
            detail = (
                "Profile này không thuộc power-profiles-daemon; dùng privileged "
                "helper với read-back 2,75 giây."
            )
            if not self.profile_client.available:
                reason = self.profile_client.unavailable_reason
                detail = reason if isinstance(reason, str) else "Privileged helper chưa khả dụng hoặc cần cập nhật."
            elif profile == "custom":
                detail = "Thermal profile firmware, không phải fan curve/manual RPM. Cần AC, BIOS auto và CPU/GPU ≤ 50 °C; chọn Tiết kiệm để hạ nhiệt trước."
        else:
            detail = power_state.warning(profile) or (
                "Đổi qua power-profiles-daemon và xác minh cả PPD lẫn Alienware "
                "platform profile; BIOS / EC vẫn kiểm soát quạt."
            )
        return control_status(
            selected=selected,
            busy=self._profile_change_busy(),
            block_reason=None if record_only else blocked,
            available=record_only or transport_available,
            detail=detail,
            selected_label="Đang chọn" if preset else "Đang dùng",
        )

    def _tick(self) -> bool:
        self.refresh()
        return GLib.SOURCE_CONTINUE

    def _schedule_refresh(self) -> None:
        if self.refresh_source_id is not None:
            GLib.source_remove(self.refresh_source_id)
        self.refresh_source_id = GLib.timeout_add_seconds(
            self.settings.refresh_seconds, self._tick
        )

    def refresh(self) -> None:
        if self.closed:
            return
        # Updating cached controls is cheap and keeps busy indicators immediate.
        if self.last_snapshot is not None:
            self._render(self.last_snapshot)
        self.poller.request(self._snapshot_ready, self._snapshot_failed)

    def _read_snapshot(self) -> DashboardSnapshot:
        return DashboardSnapshot(self.backend.snapshot(), self.resource_reader.read())

    def _snapshot_ready(self, snapshot: DashboardSnapshot) -> None:
        if self.closed:
            return
        scroll_anchor = self._scroll_anchor()
        self.last_snapshot = snapshot.hardware
        self.resources = snapshot.resources
        self._render(snapshot.hardware)
        if scroll_anchor is not None:
            self._restore_scroll_anchor(*scroll_anchor)

    def _snapshot_failed(self, error: str) -> None:
        self.notify(f"Không đọc được telemetry: {error}")

    def close(self) -> bool:
        self.closed = True
        self.fan_client.close()
        self.poller.close()
        for source in (self.refresh_source_id, self.scroll_restore_source_id):
            if source is not None:
                GLib.source_remove(source)
        self.refresh_source_id = self.scroll_restore_source_id = None
        return False

    def _scroll_anchor(self) -> tuple[float, bool] | None:
        adjustment = self.get_vadjustment()
        maximum = max(adjustment.get_upper() - adjustment.get_page_size(), 0.0)
        # Before the first allocation there is no meaningful user position to
        # restore.  Restoring that value after layout would jump the initial
        # view to the bottom.
        if maximum <= 0:
            return None
        value = adjustment.get_value()
        return value, value >= maximum - 2.0

    def _restore_scroll_anchor(self, value: float, was_at_bottom: bool) -> None:
        if self.scroll_restore_source_id is not None:
            GLib.source_remove(self.scroll_restore_source_id)

        def restore() -> bool:
            self.scroll_restore_source_id = None
            adjustment = self.get_vadjustment()
            adjustment.set_value(
                scroll_restore_target(
                    value,
                    adjustment.get_upper(),
                    adjustment.get_page_size(),
                    was_at_bottom,
                )
            )
            return GLib.SOURCE_REMOVE

        # Preserve the anchor when discovery changes the set of visible rows.
        self.scroll_restore_source_id = GLib.idle_add(restore)

    def _render(self, state: SystemSnapshot) -> None:
        self.system_label.set_text(
            f"{state.model or 'Không rõ model'}  •  BIOS {state.bios_version or '—'}  •  Kernel {state.kernel}"
        )
        cap = state.capabilities
        power_state = self.power_client.refresh()
        if cap.external_awccd_controller:
            self.banner.set_title("Xung đột controller: awccd đang ghi profile và fan boost")
        elif self.fan_client.state.running:
            self.banner.set_title(self.fan_client.state.message)
        elif cap.stable_manual_fan_control:
            self.banner.set_title("Manual fan control đã được xác minh")
        else:
            self.banner.set_title("Chế độ an toàn: BIOS / EC vẫn kiểm soát quạt")

        self._sync_sensor_cards(state)
        resources = self.resources
        cpu_clock = f"{resources.cpu_mhz / 1000:.2f} GHz" if resources.cpu_mhz is not None else "—"
        cpu_usage = f"{resources.cpu_percent:.0f} %" if resources.cpu_percent is not None else "—"
        self.cpu_usage_card.update(
            f"{cpu_clock} / {cpu_usage}",
            "Xung trung bình các luồng · tải toàn CPU" if resources.cpu_percent is not None
            else "Đang lấy mẫu tải CPU…" if resources.cpu_mhz is not None else "Không có dữ liệu hợp lệ",
        )
        gpu_clock = f"{resources.gpu_mhz:.0f} MHz" if resources.gpu_mhz is not None else "—"
        gpu_usage = f"{resources.gpu_percent:.0f} %" if resources.gpu_percent is not None else "—"
        self.gpu_usage_card.update(
            f"{gpu_clock} / {gpu_usage}",
            "NVIDIA GPU 0 · xung đồ họa / mức sử dụng" if resources.gpu_mhz is not None or resources.gpu_percent is not None
            else "Không có dữ liệu NVIDIA hợp lệ",
        )
        gib = 1024 ** 3
        ram_used = f"{resources.ram_used_bytes / gib:.1f}" if resources.ram_used_bytes is not None else "—"
        ram_total = f"{resources.ram_total_bytes / gib:.1f} GiB" if resources.ram_total_bytes is not None else "—"
        ram_percent = (
            f"{100 * resources.ram_used_bytes / resources.ram_total_bytes:.0f} % đang dùng · không tính cache khả dụng"
            if resources.ram_used_bytes is not None and resources.ram_total_bytes
            else "Không có dữ liệu bộ nhớ hợp lệ"
        )
        self.ram_card.update(f"{ram_used} / {ram_total}", ram_percent)
        display_fans = state.awcc_fans or state.fans
        running = sum(1 for fan in display_fans if (fan.rpm or 0) > 0)
        source = "AWCC WMI" if state.awcc_fans else "dell_smm"
        self.fans_card.update(
            f"{running} / {len(display_fans)}", f"Kênh có RPM > 0 · {source}"
        )
        current = state.profile.current or "—"
        self.profile_card.update(PROFILE_LABELS.get(current, current), state.profile.provider or "")

        if power_state.available:
            active = power_state.active or "unknown"
            self.power_row.set_title(f"Power mode: {active}")
            self.power_row.set_subtitle(
                f"Performance bị giới hạn: {power_state.performance_degraded}"
                if power_state.performance_degraded
                else "Mode chuẩn được đổi qua power-profiles-daemon D-Bus"
            )
        else:
            self.power_row.set_title("power-profiles-daemon không khả dụng")
            self.power_row.set_subtitle("Fallback sang privileged helper có read-back")

        for preset in PRESETS:
            preset_active = (
                self.settings.preferred_preset == "auto"
                if preset.profile is None
                else preset.profile == state.profile.current
                and self.settings.preferred_preset != "auto"
            )
            status = self._profile_status(state, preset.profile, preset_active, preset=True)
            if preset.key not in self.preset_cards:
                button = Gtk.ToggleButton()
                card = self._control_card(preset.label, preset.description, status, button, "Chọn preset")
                button.connect("clicked", self._request_preset, preset)
                self.preset_box.insert(card, -1)
                self.preset_cards[preset.key] = card
            self._update_control_card(self.preset_cards[preset.key], preset.label, status, "Chọn preset")

        for profile in tuple(self.profile_cards):
            if profile not in state.profile.choices:
                card = self.profile_cards.pop(profile)
                self.profile_box.remove(card.get_parent())
        for profile in state.profile.choices:
            status = self._profile_status(state, profile, profile == state.profile.current)
            if profile not in self.profile_cards:
                button = Gtk.ToggleButton()
                card = self._control_card(PROFILE_LABELS.get(profile, profile), "", status, button, "Áp dụng profile")
                button.connect("clicked", self._request_profile, profile)
                self.profile_box.insert(card, -1)
                self.profile_cards[profile] = card
            self._update_control_card(self.profile_cards[profile], PROFILE_LABELS.get(profile, profile), status, "Áp dụng profile")

        fan_entries = []
        if state.awcc_fans:
            for fan in state.awcc_fans:
                boost = f"{fan.boost}/255" if fan.boost is not None else "—"
                sensor = (
                    f" · temp{fan.temperature_channel}"
                    if fan.temperature_channel is not None
                    else ""
                )
                reference = (
                    f" · fan_max ref {fan.max_rpm}"
                    if fan.max_rpm is not None
                    else ""
                )
                rpm = fan.rpm if fan.rpm is not None else "—"
                fan_entries.append((("awcc", fan.channel), f"{fan.label} · AWCC kênh {fan.channel}", f"Boost raw {boost}{sensor}{reference}", f"{rpm} RPM"))
        else:
            for fan in state.fans:
                target = (
                    f" · target {fan.target_rpm} RPM"
                    if fan.target_rpm is not None
                    else ""
                )
                fan_entries.append((("dell", fan.channel), f"{fan.label} · dell_smm kênh {fan.channel}", f"{fan.control_label}{target}", f"{fan.rpm if fan.rpm is not None else '—'} RPM"))
        self._sync_rows(self.fan_list, self.fan_rows, fan_entries)
        self._render_fan_controls(state)

        self.control_row.remove_css_class("success")
        self.control_row.remove_css_class("warning")
        self.control_row.add_css_class(_status_css(cap.control_state))
        labels = {
            ControlState.BIOS_AUTO: "BIOS / EC đang kiểm soát",
            ControlState.MANUAL: "Driver báo manual — chưa xác minh độ ổn định",
            ControlState.MIXED: "Trạng thái điều khiển hỗn hợp",
            ControlState.UNKNOWN: "Không xác định được quyền điều khiển",
            ControlState.UNAVAILABLE: "Không có backend quạt",
        }
        self.control_row.set_title(
            "Controller bên ngoài đang hoạt động"
            if cap.external_awccd_controller
            else labels[cap.control_state]
        )
        self.control_row.set_subtitle(" ".join(cap.reasons))
        if self.fan_client.state.running:
            self.control_row.set_title("Phiên AWCC boost có watchdog — không phải SMM manual")
            self.control_row.set_subtitle(self.fan_client.state.message)

    def _fan_changed(self):
        if not self.closed and self.last_snapshot is not None:
            # Keep controls immediately responsive; never perform a hardware read here.
            self._render(self.last_snapshot)

    def _render_fan_controls(self, state):
        client = self.fan_client
        status = client.state
        reason = client.unavailable_reason
        custom = state.profile.current == "custom"
        self.fan_start.set_sensitive(bool(custom and not self._profile_change_busy() and reason is None))
        self.fan_stop.set_sensitive(status.running)
        if status.running:
            detail = f"{status.message} · Còn {status.remaining:.0f} giây."
        else:
            detail = reason or status.message
            detail += " Chọn Custom trước; raw 0–255, một kênh khác 100 mỗi lần. Chỉ 64/100 đã kiểm chứng RPM; raw không phải % RPM."
        self.fan_session_label.set_text(detail)
        for channel in tuple(self.fan_sliders):
            if ("awcc", channel) not in self.fan_rows:
                del self.fan_sliders[channel]
                del self.fan_apply[channel]
                self.fan_desired.pop(channel, None)
        for fan in state.awcc_fans:
            if fan.channel not in (1, 2, 3, 4):
                continue
            channel = fan.channel
            if channel not in self.fan_sliders:
                slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 255, 1)
                slider.set_draw_value(True)
                slider.set_digits(0)
                slider.set_size_request(160, -1)
                slider.add_mark(0, Gtk.PositionType.BOTTOM, "raw 0")
                slider.add_mark(255, Gtk.PositionType.BOTTOM, "raw 255")
                slider.set_value(100)
                slider.connect("value-changed", self._fan_slider_changed, channel)
                apply = Gtk.Button(label="Áp dụng")
                apply.set_valign(Gtk.Align.CENTER)
                apply.connect("clicked", self._apply_fan, channel)
                box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
                box.append(slider)
                box.append(apply)
                self.fan_rows[("awcc", channel)][0].add_suffix(box)
                self.fan_sliders[channel] = slider
                self.fan_apply[channel] = apply
                self.fan_desired[channel] = 100
            enabled = bool(custom and status.ready and not status.pending and reason is None)
            self.fan_sliders[channel].set_sensitive(enabled)
            self.fan_apply[channel].set_sensitive(enabled and time.monotonic() >= status.cooldown_until
                                                 and self.fan_desired[channel] != status.levels[channel - 1])
            self.fan_sliders[channel].set_tooltip_text(
                "Raw 0–255, không phải % RPM; ngoài 64/100 chưa kiểm chứng. Quạt dừng/nóng sẽ khôi phục. Ba kênh khác giữ 100."
                if enabled else reason or "Chỉ dùng trong phiên Custom đã được helper xác nhận."
            )

    def _fan_slider_changed(self, slider, channel):
        if self._syncing_fan_slider:
            return
        raw = min(255, max(0, int(round(slider.get_value()))))
        self._syncing_fan_slider = True
        slider.set_value(raw)
        self._syncing_fan_slider = False
        self.fan_desired[channel] = raw  # Selecting a value is NOT a hardware write.
        if self.last_snapshot is not None:
            self._render_fan_controls(self.last_snapshot)

    def _start_fans(self, _button):
        if (self.last_snapshot is None or self.last_snapshot.profile.current != "custom"
                or self._profile_change_busy()):
            self.notify("Chọn Custom và chờ thao tác profile hoàn tất trước.")
            return
        if self.fan_client.start():
            self._syncing_fan_slider = True
            for channel, slider in self.fan_sliders.items():
                self.fan_desired[channel] = 100
                slider.set_value(100)
            self._syncing_fan_slider = False
        else:
            self.notify(self.fan_client.unavailable_reason or "Chưa thể bắt đầu phiên quạt.")

    def _apply_fan(self, _button, channel):
        if self.last_snapshot is None or self.last_snapshot.profile.current != "custom":
            self.notify("Không được ghi quạt ngoài Custom.")
            return
        if not self.fan_client.available or not self.fan_client.state.ready:
            self.notify(self.fan_client.unavailable_reason or "Chưa có phiên quạt đã xác nhận.")
            return
        self.fan_client.set_boost(channel, self.fan_desired.get(channel, 100))

    def _request_profile(self, _button: Gtk.Button, profile: str) -> None:
        state = self.last_snapshot
        if state is None:
            self.notify("Chưa có snapshot hệ thống.")
            return
        status = self._profile_status(state, profile, profile == state.profile.current)
        if status.selected or not status.enabled:
            self.notify(status.detail)
            self.refresh()
            return
        started = self._set_profile(profile, self._profile_finished)
        if started:
            self.notify(f"Đang yêu cầu profile {PROFILE_LABELS.get(profile, profile)}…")
            self.refresh()

    def _profile_finished(self, result: ClientResult | PowerProfileResult) -> None:
        self.notify(result.message)
        self.refresh()

    def _profile_change_busy(self) -> bool:
        return self.profile_client.busy or self.power_client.busy or self.fan_client.state.running

    def _set_profile(self, profile: str, callback) -> bool:
        if self.fan_client.state.running:
            self.notify("Dừng và khôi phục phiên quạt trước khi đổi profile.")
            return False
        if self.power_client.state.supports_platform_profile(profile):
            return self.power_client.set_platform_profile(profile, callback)
        return self.profile_client.set_profile(profile, callback)

    def _request_preset(self, _button: Gtk.Button, preset: Preset) -> None:
        state = self.last_snapshot
        if state is None:
            self.notify("Chưa có snapshot hệ thống để áp dụng preset.")
            return

        status = self._profile_status(state, preset.profile, False, preset=True)
        if not status.enabled:
            self.notify(status.detail)
            self.refresh()
            return

        if preset.key == self.settings.preferred_preset and (
            preset.profile is None or preset.profile == state.profile.current
        ):
            self.notify("Preset này đang được chọn; không gửi lệnh phần cứng.")
            self.refresh()
            return

        if preset.profile is None or preset.profile == state.profile.current:
            self._save_settings(
                AppSettings(
                    preset.key,
                    self.settings.refresh_seconds,
                ),
                f"Đã chọn preset {preset.label}; không có hardware write.",
            )
            self.refresh()
            return

        self.pending_preset = preset.key
        started = self._set_profile(
            preset.profile,
            lambda result: self._preset_finished(preset, result),
        )
        if started:
            self.notify(f"Đang áp dụng preset {preset.label}…")
            self.refresh()
        else:
            self.pending_preset = None

    def _preset_finished(
        self,
        preset: Preset,
        result: ClientResult | PowerProfileResult,
    ) -> None:
        self.pending_preset = None
        if result.ok:
            self._save_settings(
                AppSettings(
                    preset.key,
                    self.settings.refresh_seconds,
                ),
                result.message,
            )
        else:
            self.notify(result.message)
        self.refresh()

    def _refresh_changed(self, row: Adw.ComboRow, _parameter) -> None:
        index = row.get_selected()
        if index >= len(REFRESH_OPTIONS):
            return
        seconds = REFRESH_OPTIONS[index]
        if seconds == self.settings.refresh_seconds:
            return
        self._save_settings(
            AppSettings(
                self.settings.preferred_preset,
                seconds,
            ),
            f"Chu kỳ làm mới: {seconds} giây.",
        )
        self._schedule_refresh()

    def _save_settings(self, settings: AppSettings, message: str) -> None:
        try:
            self.settings_store.save(settings)
        except OSError as exc:
            self.notify(f"Không lưu được cài đặt: {exc}")
            return
        self.settings = settings.normalized()
        self.notify(message)


CSS = b"""
window { background: @window_bg_color; }
.metric-card {
  min-width: 180px;
  padding: 18px;
  border-radius: 14px;
  background: @card_bg_color;
  box-shadow: 0 1px 3px alpha(black, .12);
}
.metric-value { font-size: 25px; font-weight: 700; }
.control-card {
  min-width: 190px;
  padding: 14px;
  border-radius: 12px;
  border: 1px solid alpha(@window_fg_color, .16);
  background: @card_bg_color;
}
.control-badge { font-weight: 650; }
.control-selected { border-color: @accent_bg_color; }
.control-selected .control-badge { color: @accent_color; }
.control-blocked .control-badge, .control-unavailable .control-badge { color: @warning_color; }
.numeric { font-feature-settings: 'tnum'; font-weight: 650; }
.warning { color: @warning_color; }
.success { color: @success_color; }
"""


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application, backend: HardwareBackend) -> None:
        super().__init__(application=application)
        self.set_title("Alienware Control Center")
        self.set_default_size(980, 780)
        self.set_size_request(720, 560)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        title = Adw.WindowTitle(title="Alienware Control Center", subtitle="Linux · safe hardware backend")
        header.set_title_widget(title)
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Làm mới")
        header.pack_end(refresh)
        overlay = Adw.ToastOverlay()

        def notify(message: str) -> None:
            overlay.add_toast(Adw.Toast.new(message))

        dashboard = Dashboard(backend, notify)
        self.connect("close-request", lambda *_args: dashboard.close())
        refresh.connect("clicked", lambda _button: dashboard.refresh())
        overlay.set_child(dashboard)
        toolbar.add_top_bar(header)
        toolbar.set_content(overlay)
        self.set_content(toolbar)

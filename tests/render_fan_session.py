"""Visual QA fixture only: fake transport, no authentication or hardware writes."""
from pathlib import Path
from unittest.mock import Mock
import sys

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Gdk, GLib, Graphene, Gtk

from awcc_linux.fan_client import FanClientState
from awcc_linux.ui import CSS
from test_fan_session import snapshot
from test_ui_controls import DashboardControlTests


def main():
    fixture = DashboardControlTests()
    fixture.setUp()
    client = Mock(available=True, unavailable_reason=None)
    client.state = FanClientState(running=True, ready=True, remaining=42,
                                  message="Mô phỏng giao diện — KHÔNG ghi phần cứng")
    fixture.dashboard.fan_client = client
    state = snapshot("custom", dict.fromkeys(range(1, 5), 100))
    fixture.backend.snapshot.return_value = state
    fixture.dashboard.refresh()
    fixture.dashboard.fan_sliders[3].set_value(64)  # Pending selection only, no apply/write.
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    window = Gtk.Window(title="AWCC fan session — simulated, no hardware writes")
    window.set_default_size(980, 900)
    window.set_child(fixture.dashboard)
    window.present()
    loop = GLib.MainLoop()
    result = [1]

    def capture():
        try:
            destination = Path(__file__).resolve().parents[1]/"research/results/ui-fan-session-2026-10-15"
            destination.mkdir(parents=True, exist_ok=True)
            for name, widget in (("fans-active", fixture.dashboard.fan_list),
                                 ("session-status", fixture.dashboard.fan_session_label.get_parent())):
                canvas = Gtk.Snapshot()
                _, color = widget.get_style_context().lookup_color("window_bg_color")
                bounds = Graphene.Rect()
                bounds.init(0, 0, widget.get_width(), widget.get_height())
                canvas.append_color(color, bounds)
                Gtk.WidgetPaintable.new(widget).snapshot(canvas, widget.get_width(), widget.get_height())
                node = canvas.to_node()
                if node is None:
                    raise RuntimeError("No render node")
                texture = window.get_renderer().render_texture(node, None)
                output = destination/f"{name}.png"
                if not texture.save_to_png(str(output)):
                    raise RuntimeError("PNG save failed")
                print(output)
            fixture.assert_no_hardware_requests()
            client.start.assert_not_called()
            client.set_boost.assert_not_called()
            result[0] = 0
        except Exception as exc:
            print(repr(exc), file=sys.stderr)
        finally:
            window.destroy()
            fixture.doCleanups()
            loop.quit()
        return False

    GLib.timeout_add(1000, capture)
    loop.run()
    return result[0]


if __name__ == "__main__":
    raise SystemExit(main())

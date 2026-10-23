"""Render only our GTK controls for visual QA using the no-write test fixture."""
from __future__ import annotations

from pathlib import Path
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Gdk, GLib, Graphene, Gtk

from test_ui_controls import DashboardControlTests
from awcc_linux.ui import CSS


def main() -> int:
    fixture = DashboardControlTests()
    fixture.setUp()
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    window = Gtk.Window(title="AWCC · kiểm tra giao diện, không ghi phần cứng")
    window.set_default_size(980, 780)
    window.set_child(fixture.dashboard)
    window.present()
    loop = GLib.MainLoop()
    result = [1]

    def capture():
        try:
            destination = Path(__file__).resolve().parents[1] / "research/results/ui-reliability-2026-10-13"
            destination.mkdir(parents=True, exist_ok=True)
            for name, widget in (
                ("preset", fixture.dashboard.preset_box),
                ("sensors", fixture.dashboard.metrics),
                ("fans", fixture.dashboard.fan_list),
                ("profiles", fixture.dashboard.profile_box),
            ):
                snapshot = Gtk.Snapshot()
                width, height = widget.get_width(), widget.get_height()
                found, background = widget.get_style_context().lookup_color("window_bg_color")
                if not found:
                    raise RuntimeError("Missing window background color")
                bounds = Graphene.Rect()
                bounds.init(0, 0, width, height)
                snapshot.append_color(background, bounds)
                Gtk.WidgetPaintable.new(widget).snapshot(snapshot, width, height)
                node = snapshot.to_node()
                if node is None:
                    raise RuntimeError(f"No render node for {name}")
                texture = window.get_renderer().render_texture(node, None)
                target = destination / f"ui-{name}-status.png"
                if not texture.save_to_png(str(target)):
                    raise RuntimeError(f"Could not save {target}")
                print(f"Rendered {target}: {width}x{height}", flush=True)
            fixture.assert_no_hardware_requests()
            result[0] = 0
        except Exception as exc:
            print(f"Visual QA failed: {exc!r}", file=sys.stderr, flush=True)
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

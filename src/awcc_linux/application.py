from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from .backend import HardwareBackend
from .ui import CSS, MainWindow


class AlienwareApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id="io.github.awcclinux.ControlCenter")

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def do_activate(self) -> None:
        window = self.get_active_window()
        if window is None:
            window = MainWindow(self, HardwareBackend())
        window.present()


def main() -> int:
    Adw.init()
    return AlienwareApplication().run(sys.argv)

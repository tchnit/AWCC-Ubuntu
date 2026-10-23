"""Packaging checks that do not install or launch the desktop application."""
from __future__ import annotations

import configparser
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DesktopPackagingTests(unittest.TestCase):
    def test_project_exposes_the_desktop_entry_point(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(project["project"]["name"], "alienware-control-center-linux")
        self.assertEqual(
            project["project"]["scripts"]["alienware-control-center"],
            "awcc_linux.application:main",
        )

    def test_desktop_file_runs_the_packaged_entry_point(self) -> None:
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(ROOT / "data/io.github.awcclinux.ControlCenter.desktop", encoding="utf-8")
        entry = parser["Desktop Entry"]
        self.assertEqual(entry["Type"], "Application")
        self.assertEqual(entry["Exec"], "alienware-control-center")
        self.assertEqual(entry["Terminal"], "false")

    def test_user_scope_installer_never_escalates_or_touches_helper(self) -> None:
        installer = ROOT / "tools/install-desktop.sh"
        source = installer.read_text(encoding="utf-8")
        self.assertTrue(installer.stat().st_mode & stat.S_IXUSR)
        checked = subprocess.run(["bash", "-n", str(installer)], check=False)
        self.assertEqual(checked.returncode, 0)
        self.assertIn("-m venv --system-site-packages", source)
        self.assertIn("--no-deps --no-build-isolation --wheel-dir", source)
        self.assertIn("--no-index --no-deps --force-reinstall", source)
        self.assertIn("XDG_DATA_HOME", source)
        self.assertIn('if [[ "${line}" == Exec=* ]]', source)
        self.assertNotIn("pkexec", source)
        self.assertNotIn("sudo", source)
        self.assertNotIn("--break-system-packages", source)
        self.assertNotIn("awcc-profile-helper", source)

    def test_installed_desktop_entry_accepts_launcher_path_with_spaces(self) -> None:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "My Apps"
            fake_python = root / "fake-python"
            fake_python.write_text('''#!/usr/bin/env python3
from pathlib import Path
import sys
args = sys.argv[1:]
if args[:2] == ["-m", "pip"] and "--wheel-dir" in args:
    (Path(args[args.index("--wheel-dir") + 1]) / "fake.whl").touch()
elif args[:2] == ["-m", "venv"]:
    bin_dir = Path(args[-1]) / "bin"
    bin_dir.mkdir(parents=True)
    for name in ("pip", "alienware-control-center"):
        launcher = bin_dir / name
        launcher.write_text("#!/bin/sh\\nexit 0\\n")
        launcher.chmod(0o755)
''')
            fake_python.chmod(0o755)
            env = {**os.environ, "PYTHON_BIN": str(fake_python), "XDG_DATA_HOME": str(data), "TMPDIR": directory}
            completed = subprocess.run(["bash", str(ROOT / "tools/install-desktop.sh")], env=env,
                                       capture_output=True, text=True, timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            entry = data / "applications/io.github.awcclinux.ControlCenter.desktop"
            app = Gio.DesktopAppInfo.new_from_filename(str(entry))
            self.assertIsNotNone(app, entry.read_text())


if __name__ == "__main__":
    unittest.main()

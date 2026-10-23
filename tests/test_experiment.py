from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from awcc_linux.experiment import ExperimentPreflight


def write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class ExperimentPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        write(self.root, "class/dmi/id/sys_vendor", "Alienware\n")
        write(self.root, "class/dmi/id/product_name", "Alienware x17 R1\n")
        write(self.root, "class/power_supply/ACAD/type", "Mains\n")
        write(self.root, "class/power_supply/ACAD/online", "1\n")
        write(self.root, "class/hwmon/hwmon8/name", "dell_smm\n")
        for channel in range(1, 5):
            write(self.root, f"class/hwmon/hwmon8/fan{channel}_input", "4000\n")
            write(self.root, f"class/hwmon/hwmon8/pwm{channel}_enable", "2\n")
        write(self.root, "class/hwmon/hwmon8/temp1_label", "CPU\n")
        write(self.root, "class/hwmon/hwmon8/temp1_input", "45000\n")
        write(self.root, "class/platform-profile/platform-profile-0/name", "alienware-wmi\n")
        write(self.root, "class/platform-profile/platform-profile-0/profile", "balanced\n")
        write(self.root, "class/platform-profile/platform-profile-0/choices", "quiet balanced\n")
        (self.root / "module/dell_smm_hwmon").mkdir(parents=True)
        self.candidate = self.root / "candidate.ko"
        self.candidate.write_bytes(b"test")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_ready_when_all_read_only_gates_pass(self) -> None:
        report = ExperimentPreflight(self.root, self.candidate).run()
        self.assertTrue(report.ready)
        self.assertFalse(report.failures)

    def test_hot_system_fails_closed(self) -> None:
        write(self.root, "class/hwmon/hwmon8/temp1_input", "65000\n")
        report = ExperimentPreflight(self.root, self.candidate).run()
        self.assertFalse(report.ready)
        self.assertIn("temperature-headroom", {item.name for item in report.failures})

    def test_battery_power_fails_closed(self) -> None:
        write(self.root, "class/power_supply/ACAD/online", "0\n")
        report = ExperimentPreflight(self.root, self.candidate).run()
        self.assertFalse(report.ready)
        self.assertIn("ac-power", {item.name for item in report.failures})


if __name__ == "__main__":
    unittest.main()

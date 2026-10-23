from __future__ import annotations

import tempfile
import math
import unittest
from pathlib import Path
from unittest.mock import patch

from awcc_linux.backend import HardwareBackend
from awcc_linux.discovery import discover, find_hwmon
from awcc_linux.models import ControlState, Temperature


def write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class BackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        write(self.root, "class/hwmon/hwmon4/name", "alienware_wmi\n")
        write(self.root, "class/hwmon/hwmon4/fan1_label", "CPU Fan\n")
        write(self.root, "class/hwmon/hwmon4/fan1_input", "3900\n")
        write(self.root, "class/hwmon/hwmon4/fan1_min", "0\n")
        write(self.root, "class/hwmon/hwmon4/fan1_max", "4100\n")
        write(self.root, "class/hwmon/hwmon4/fan1_boost", "128\n")
        write(self.root, "class/hwmon/hwmon4/pwm1_auto_channels_temp", "1\n")
        write(self.root, "class/hwmon/hwmon4/temp1_label", "CPU\n")
        write(self.root, "class/hwmon/hwmon4/temp1_input", "50000\n")
        write(self.root, "class/hwmon/hwmon4/temp2_label", "GPU\n")
        write(self.root, "class/hwmon/hwmon4/temp2_input", "47000\n")
        write(self.root, "class/hwmon/hwmon9/name", "dell_smm\n")
        write(self.root, "class/hwmon/hwmon9/fan1_label", "Processor Fan\n")
        write(self.root, "class/hwmon/hwmon9/fan1_input", "4100\n")
        write(self.root, "class/hwmon/hwmon9/fan1_target", "4000\n")
        write(self.root, "class/hwmon/hwmon9/pwm1_enable", "2\n")
        write(self.root, "class/hwmon/hwmon9/temp1_label", "CPU\n")
        write(self.root, "class/hwmon/hwmon9/temp1_input", "51500\n")
        write(self.root, "class/platform-profile/platform-profile-3/name", "alienware-wmi\n")
        write(self.root, "class/platform-profile/platform-profile-3/profile", "balanced\n")
        write(self.root, "class/platform-profile/platform-profile-3/choices", "quiet balanced performance\n")
        write(self.root, "class/dmi/id/product_name", "Alienware x17 R1\n")
        write(self.root, "class/dmi/id/bios_version", "1.27.0\n")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_dynamic_hwmon_discovery(self) -> None:
        found = find_hwmon(self.root / "class/hwmon", "dell_smm")
        self.assertEqual(found, self.root / "class/hwmon/hwmon9")
        paths = discover(self.root)
        self.assertEqual(paths.alienware_hwmon, self.root / "class/hwmon/hwmon4")

    def test_platform_profile_uses_alienware_provider_not_first_directory(self) -> None:
        write(self.root, "class/platform-profile/platform-profile-1/name", "other-driver\n")
        write(self.root, "class/platform-profile/platform-profile-1/profile", "balanced\n")
        write(self.root, "class/platform-profile/platform-profile-1/choices", "balanced\n")

        paths = discover(self.root)

        self.assertEqual(
            paths.platform_profile,
            self.root / "class/platform-profile/platform-profile-3",
        )

    def test_unrelated_platform_profile_is_not_exposed_as_alienware(self) -> None:
        write(self.root, "class/platform-profile/platform-profile-3/name", "other-driver\n")

        snapshot = HardwareBackend(self.root).snapshot()

        self.assertIsNone(snapshot.profile.current)
        self.assertFalse(snapshot.capabilities.platform_profiles)
        self.assertTrue(any("platform profile" in warning for warning in snapshot.warnings))

    def test_snapshot_reads_verified_fields(self) -> None:
        snapshot = HardwareBackend(self.root).snapshot()
        self.assertEqual(snapshot.model, "Alienware x17 R1")
        self.assertEqual(snapshot.profile.current, "balanced")
        self.assertEqual(snapshot.fans[0].rpm, 4100)
        self.assertEqual(snapshot.fans[0].target_rpm, 4000)
        self.assertEqual(snapshot.awcc_fans[0].label, "CPU Fan")
        self.assertEqual(snapshot.awcc_fans[0].boost, 128)
        self.assertAlmostEqual(snapshot.awcc_fans[0].boost_percent or 0, 50.2, places=1)
        self.assertEqual(snapshot.awcc_fans[0].temperature_channel, 1)
        self.assertEqual(snapshot.temperatures[0].celsius, 50.0)
        self.assertEqual(snapshot.temperatures[0].source, "AWCC WMI")
        self.assertEqual(snapshot.temperatures[1].label, "GPU")
        self.assertEqual(snapshot.capabilities.control_state, ControlState.BIOS_AUTO)
        self.assertTrue(snapshot.capabilities.awcc_fan_boost)
        self.assertFalse(snapshot.capabilities.stable_manual_fan_control)

    def test_nvidia_gpu_telemetry_takes_priority_over_bad_wmi_gpu_channel(self) -> None:
        nvidia = (Temperature(1, "GPU", 47.0, "NVIDIA NVML"),)

        snapshot = HardwareBackend(
            self.root,
            nvidia_temperature_reader=lambda: nvidia,
        ).snapshot()

        gpu = next(sensor for sensor in snapshot.temperatures if sensor.label == "GPU")
        self.assertEqual(gpu.celsius, 47.0)
        self.assertEqual(gpu.source, "NVIDIA NVML")
        self.assertFalse(any(
            sensor.label == "GPU" and sensor.source == "AWCC WMI"
            for sensor in snapshot.temperatures
        ))

    def test_awcc_only_is_still_valid_telemetry(self) -> None:
        write(self.root, "class/hwmon/hwmon9/name", "unrelated-provider\n")
        snapshot = HardwareBackend(self.root).snapshot()
        self.assertTrue(snapshot.capabilities.telemetry)
        self.assertEqual(snapshot.capabilities.control_state, ControlState.UNKNOWN)
        self.assertTrue(snapshot.awcc_fans)
        self.assertTrue(snapshot.temperatures)

    def test_bad_gpu_fallback_is_hidden_when_nvml_unavailable(self):
        write(self.root, "class/hwmon/hwmon4/temp2_input", "2000\n")
        snapshot = HardwareBackend(self.root, nvidia_temperature_reader=lambda: ()).snapshot()
        self.assertFalse(any(sensor.label == "GPU" for sensor in snapshot.temperatures))
        self.assertTrue(any("GPU" in warning for warning in snapshot.warnings))

    def test_nonfinite_gpu_sample_is_not_displayed(self):
        snapshot = HardwareBackend(self.root, nvidia_temperature_reader=lambda: (Temperature(1, "GPU", float("nan"), "NVIDIA NVML"),)).snapshot()
        self.assertTrue(all(math.isfinite(sensor.celsius) for sensor in snapshot.temperatures))

    def test_invalid_preferred_gpu_does_not_hide_valid_secondary_sensor(self):
        write(self.root, "class/hwmon/hwmon4/temp2_input", "2000\n")
        write(self.root, "class/hwmon/hwmon9/temp2_label", "GPU\n")
        write(self.root, "class/hwmon/hwmon9/temp2_input", "49000\n")
        snapshot = HardwareBackend(self.root, nvidia_temperature_reader=lambda: ()).snapshot()
        gpu = next(sensor for sensor in snapshot.temperatures if sensor.label == "GPU")
        self.assertEqual((gpu.celsius, gpu.source), (49, "dell_smm"))

    def test_temperature_only_is_valid_telemetry(self) -> None:
        write(self.root, "class/hwmon/hwmon4/name", "unrelated-provider\n")
        write(self.root, "class/hwmon/hwmon9/name", "dell_smm\n")
        for relative in (
            "class/hwmon/hwmon9/fan1_input",
            "class/hwmon/hwmon9/fan1_label",
            "class/hwmon/hwmon9/fan1_target",
            "class/hwmon/hwmon9/pwm1_enable",
        ):
            (self.root / relative).unlink()
        snapshot = HardwareBackend(self.root).snapshot()
        self.assertFalse(snapshot.fans)
        self.assertFalse(snapshot.awcc_fans)
        self.assertTrue(snapshot.temperatures)
        self.assertTrue(snapshot.capabilities.telemetry)

    def test_missing_sysfs_degrades_cleanly(self) -> None:
        empty = Path(self.tempdir.name) / "empty"
        empty.mkdir()
        snapshot = HardwareBackend(empty).snapshot()
        self.assertFalse(snapshot.capabilities.telemetry)
        self.assertEqual(snapshot.capabilities.control_state, ControlState.UNAVAILABLE)
        self.assertTrue(snapshot.warnings)

    def test_external_awccd_socket_is_reported_without_connecting(self) -> None:
        socket_path = self.root / "run/awcc/awccd.sock"
        socket_path.parent.mkdir(parents=True)
        socket_path.touch()

        with patch.object(Path, "is_socket", return_value=True):
            snapshot = HardwareBackend(self.root, runtime_root=self.root).snapshot()

        self.assertTrue(snapshot.capabilities.external_awccd_controller)
        self.assertTrue(any("awccd" in warning for warning in snapshot.warnings))
        self.assertTrue(any("awccd" in reason for reason in snapshot.capabilities.reasons))


if __name__ == "__main__":
    unittest.main()

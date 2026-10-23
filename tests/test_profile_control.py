from __future__ import annotations

import subprocess
import tempfile
import socket
import unittest
import threading
from pathlib import Path
from unittest.mock import patch
from awcc_linux import fan_hardware, profile_control as control
from awcc_linux.profile_recovery import acquire_singleton, restore_daemon

from awcc_linux.privileged import ProfileClient
from awcc_linux.profile_control import ProfileControlError, ProfileController


def write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class ProfileControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        base = "class/platform-profile/platform-profile-7"
        write(self.root, f"{base}/name", "alienware-wmi\n")
        write(
            self.root,
            f"{base}/choices",
            "low-power quiet balanced balanced-performance performance custom\n",
        )
        self.profile = write(self.root, f"{base}/profile", "balanced\n")
        write(self.root, "class/dmi/id/product_name", "Alienware x17 R1\n")
        write(self.root, "class/dmi/id/bios_version", "1.27.0\n")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_allowed_profile_is_written_and_verified(self) -> None:
        write(self.root, "class/dmi/id/bios_version", "1.28.0\n")
        result = ProfileController(self.root, sleeper=lambda _delay: None).set_profile(
            "performance", verification_delays=(0, 0)
        )
        self.assertEqual(result.previous, "balanced")
        self.assertEqual(result.observed, ("performance", "performance"))
        self.assertTrue(result.persistent)

    def test_firmware_rollback_is_reported(self) -> None:
        write(self.root, "class/dmi/id/bios_version", "1.28.0\n")

        def firmware_tick(_delay: float) -> None:
            self.profile.write_text("balanced\n", encoding="utf-8")

        result = ProfileController(self.root, sleeper=firmware_tick).set_profile(
            "performance", verification_delays=(0, 1)
        )
        self.assertEqual(result.observed, ("performance", "balanced"))
        self.assertFalse(result.persistent)
        self.assertEqual(result.final, "balanced")

    def test_failed_verification_restores_and_verifies_old_profile(self):
        def tick(_delay):
            if self.profile.read_text().strip() == "quiet":
                self.profile.write_text("low-power\n")
        result = ProfileController(self.root, sleeper=tick).set_profile("quiet", (0, 1))
        self.assertFalse(result.persistent)
        self.assertTrue(result.restored)
        self.assertEqual(result.final, "balanced")

    def test_read_error_after_write_restores_old_profile(self):
        original = control._read
        profile_reads = 0
        def read(path):
            nonlocal profile_reads
            if path == self.profile:
                profile_reads += 1
                if profile_reads == 2:
                    raise ProfileControlError("simulated read failure")
            return original(path)
        with patch.object(control, "_read", read):
            result = ProfileController(self.root, sleeper=lambda _: None).set_profile("quiet", (0, 0))
        self.assertFalse(result.persistent)
        self.assertTrue(result.restored)
        self.assertEqual(result.final, "balanced")

    def test_performance_baseline_is_restored_only_through_ppd(self):
        self.profile.write_text("performance\n")
        calls = []
        def command(args, **kwargs):
            calls.append(args)
            if args[1] == "set":
                self.profile.write_text(args[-1] + "\n")
            return subprocess.CompletedProcess(args, 0, "performance\n", "")
        def tick(_):
            if self.profile.read_text().strip() == "quiet":
                self.profile.write_text("balanced\n")
        result = ProfileController(self.root, sleeper=tick, daemon_runner=command).set_profile("quiet", (0, 1))
        self.assertFalse(result.persistent)
        self.assertTrue(result.restored)
        self.assertEqual(result.final, "performance")
        self.assertIn(["powerprofilesctl", "set", "performance"], calls)

    def test_unverified_restore_route_blocks_before_write(self):
        self.profile.write_text("performance\n")
        with self.assertRaises(ProfileControlError):
            ProfileController(self.root).set_profile("quiet")
        self.assertEqual(self.profile.read_text().strip(), "performance")

    def test_inconsistent_ppd_baseline_blocks_before_write(self):
        def command(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, "performance\n", "")
        with self.assertRaises(ProfileControlError):
            ProfileController(self.root, daemon_runner=command).set_profile("quiet")
        self.assertEqual(self.profile.read_text().strip(), "balanced")

    def test_empty_verification_window_is_rejected_before_write(self):
        with self.assertRaises(ProfileControlError):
            ProfileController(self.root).set_profile("quiet", ())
        self.assertEqual(self.profile.read_text().strip(), "balanced")

    def test_failed_recovery_reports_actual_final_profile(self):
        def tick(_delay):
            self.profile.write_text("low-power\n")
        result = ProfileController(self.root, sleeper=tick).set_profile("quiet", (0, 1))
        self.assertFalse(result.persistent)
        self.assertFalse(result.restored)
        self.assertEqual(result.final, "low-power")

    def test_custom_is_rejected_on_unvalidated_bios(self) -> None:
        write(self.root, "class/dmi/id/bios_version", "1.28.0\n")
        with self.assertRaises(ProfileControlError):
            ProfileController(self.root).set_profile("custom", verification_delays=(0,))
        self.assertEqual(self.profile.read_text(encoding="utf-8").strip(), "balanced")

    def test_verified_quiet_profile_is_written_on_tested_bios(self) -> None:
        result = ProfileController(self.root, sleeper=lambda _delay: None).set_profile(
            "quiet", verification_delays=(0, 0)
        )
        self.assertTrue(result.persistent)
        self.assertEqual(self.profile.read_text(encoding="utf-8").strip(), "quiet")

    def test_known_low_power_rollback_is_blocked_for_tested_bios(self) -> None:
        with self.assertRaises(ProfileControlError):
            ProfileController(self.root).set_profile("low-power", verification_delays=(0,))
        self.assertEqual(self.profile.read_text(encoding="utf-8").strip(), "balanced")

    def test_performance_helper_fallback_stays_blocked_on_tested_bios(self) -> None:
        with self.assertRaises(ProfileControlError):
            ProfileController(self.root).set_profile(
                "performance", verification_delays=(0,)
            )
        self.assertEqual(self.profile.read_text(encoding="utf-8").strip(), "balanced")

    def test_verified_balanced_performance_is_allowed_on_tested_bios(self) -> None:
        result = ProfileController(self.root, sleeper=lambda _:None).set_profile("balanced-performance", (0,0))
        self.assertTrue(result.persistent)
        self.assertEqual(result.final, "balanced-performance")

    def prepare_custom_sensors(self):
        write(self.root, "class/hwmon/hwmon9/name", "dell_smm\n")
        for channel in range(1,5):
            write(self.root, f"class/hwmon/hwmon9/fan{channel}_input", "2000\n")
            write(self.root, f"class/hwmon/hwmon9/pwm{channel}_enable", "2\n")
        for channel,label in ((1,"CPU"),(2,"GPU")):
            write(self.root, f"class/hwmon/hwmon9/temp{channel}_label", label)
            write(self.root, f"class/hwmon/hwmon9/temp{channel}_input", "45000\n")
        write(self.root, "class/power_supply/ACAD/online", "1\n")

    def test_custom_thermal_profile_is_allowed_with_verified_guards(self):
        self.prepare_custom_sensors()
        result=ProfileController(self.root,sleeper=lambda _:None).set_profile("custom",(0,0))
        self.assertTrue(result.persistent)
        self.assertEqual(result.final,"custom")

    def test_custom_thermal_rejects_hot_missing_ac_or_manual_fans_before_write(self):
        for relative,value in (("class/hwmon/hwmon9/temp1_input","55000"),("class/power_supply/ACAD/online","0"),("class/hwmon/hwmon9/pwm1_enable","1")):
            with self.subTest(relative=relative):
                self.prepare_custom_sensors()
                write(self.root,relative,value)
                with self.assertRaises(ProfileControlError):
                    ProfileController(self.root,sleeper=lambda _:None).set_profile("custom",(0,0))
                self.assertEqual(self.profile.read_text().strip(),"balanced")

    def test_failed_transition_from_hot_custom_recovers_to_safe_balanced(self):
        self.prepare_custom_sensors()
        self.profile.write_text("custom\n")
        def tick(_delay):
            if self.profile.read_text().strip()=="quiet":
                self.profile.write_text("performance\n")
                write(self.root,"class/hwmon/hwmon9/temp1_input","55000\n")
        result=ProfileController(self.root,sleeper=tick).set_profile("quiet",(0,1))
        self.assertFalse(result.persistent)
        self.assertFalse(result.restored)
        self.assertEqual(result.final,"balanced")
        self.assertIn("Balanced an toàn",result.error)

    def test_model_policy_does_not_guess_for_other_bios(self) -> None:
        write(self.root, "class/dmi/id/bios_version", "1.28.0\n")
        result = ProfileController(self.root, sleeper=lambda _delay: None).set_profile(
            "quiet", verification_delays=(0, 0)
        )
        self.assertTrue(result.persistent)

    def test_wrong_provider_is_rejected(self) -> None:
        write(self.root, "class/platform-profile/platform-profile-7/name", "other-driver\n")
        with self.assertRaises(ProfileControlError):
            ProfileController(self.root).set_profile("quiet", verification_delays=(0,))

    def test_profile_write_refuses_live_fan_lock(self) -> None:
        lock = self.root / "shared.lock"
        self.assertIs(fan_hardware.acquire_singleton, acquire_singleton)
        fd = acquire_singleton(lock)
        try:
            with self.assertRaises(ProfileControlError):
                ProfileController(self.root, lock_path=lock).set_profile("quiet", (0,))
            self.assertEqual(self.profile.read_text().strip(), "balanced")
        finally:
            import os
            os.close(fd)

    def test_profile_lock_covers_verification_and_recovery(self) -> None:
        lock = self.root / "shared.lock"
        checking = threading.Event()
        release = threading.Event()
        results = []
        def tick(_delay):
            if not checking.is_set():
                self.profile.write_text("low-power\n")
                checking.set()
                self.assertTrue(release.wait(2))
        def change():
            results.append(ProfileController(self.root, sleeper=tick, lock_path=lock).set_profile("quiet", (0, 1)))
        worker = threading.Thread(target=change)
        worker.start()
        try:
            self.assertTrue(checking.wait(2))
            with self.assertRaises(BlockingIOError):
                acquire_singleton(lock)
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertTrue(results[0].restored)
        fd = acquire_singleton(lock)
        import os
        os.close(fd)

    def test_competing_controller_blocks_every_profile_before_write(self) -> None:
        path = self.root / "run/awcc/awccd.sock"
        path.parent.mkdir(parents=True)
        with socket.socket(socket.AF_UNIX) as controller:
            controller.bind(str(path))
            for requested in ("quiet", "balanced-performance"):
                with self.subTest(requested=requested), self.assertRaises(ProfileControlError):
                    ProfileController(self.root, runtime_root=self.root).set_profile(requested, (0,))
                self.assertEqual(self.profile.read_text().strip(), "balanced")

    def test_active_controller_service_is_rejected(self) -> None:
        controller = ProfileController(self.root)
        controller.sys_root = Path("/sys")
        with patch.object(control.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "active\n", "")):
            with self.assertRaises(ProfileControlError):
                controller._assert_no_controller()

    def test_controller_starting_during_verification_triggers_recovery(self) -> None:
        path = self.root / "run/awcc/awccd.sock"
        path.parent.mkdir(parents=True)
        with socket.socket(socket.AF_UNIX) as controller:
            def tick(_delay):
                controller.bind(str(path))
            result = ProfileController(self.root, sleeper=tick, runtime_root=self.root).set_profile("quiet", (0, 1))
        self.assertFalse(result.persistent)
        self.assertTrue(result.restored)
        self.assertEqual(result.final, "balanced")

    def test_same_value_ppd_recovery_bridges_balanced(self) -> None:
        self.profile.write_text("balanced-performance\n")
        active = "performance"
        commands = []
        def run(args, **_kwargs):
            nonlocal active
            commands.append(args)
            if args[1] == "get":
                return subprocess.CompletedProcess(args, 0, active + "\n", "")
            if args[-1] != active:
                active = args[-1]
                self.profile.write_text(("balanced" if active == "balanced" else "performance") + "\n")
            return subprocess.CompletedProcess(args, 0, "", "")
        restored, final = restore_daemon("performance", "performance", lambda: self.profile.read_text().strip(), run, lambda _: None)
        self.assertTrue(restored)
        self.assertEqual(final, "performance")
        self.assertIn(["powerprofilesctl", "set", "balanced"], commands)

    def test_failed_ppd_bridge_retry_is_bounded(self) -> None:
        active = "performance"
        physical = "balanced-performance"
        writes = []
        def run(args, **_kwargs):
            nonlocal active, physical
            if args[1] == "get":
                return subprocess.CompletedProcess(args, 0, active + "\n", "")
            writes.append(args[-1])
            active = args[-1]
            if active == "balanced":
                physical = "balanced"
            return subprocess.CompletedProcess(args, 0, "", "")
        restored, final = restore_daemon("performance", "performance", lambda: physical, run, lambda _: None)
        self.assertFalse(restored)
        self.assertEqual(final, "balanced")
        self.assertEqual(writes, ["performance", "balanced", "performance"])

    def test_unrelated_profile_before_alienware_is_ignored(self) -> None:
        base = "class/platform-profile/platform-profile-1"
        write(self.root, f"{base}/name", "other-driver\n")
        write(self.root, f"{base}/profile", "balanced\n")
        write(self.root, f"{base}/choices", "balanced\n")

        result = ProfileController(self.root, sleeper=lambda _delay: None).set_profile(
            "quiet", verification_delays=(0, 0)
        )

        self.assertTrue(result.persistent)
        self.assertEqual(self.profile.read_text(encoding="utf-8").strip(), "quiet")


class ProfileClientResultTests(unittest.TestCase):
    def test_wrong_json_structure_and_nonzero_success_are_rejected(self):
        for code, payload in ((0, '[]'), (0, 'null'), (1, '{"ok": true}')):
            with self.subTest(code=code, payload=payload):
                result = ProfileClient._parse_result(subprocess.CompletedProcess([], code, payload, ''))
                self.assertFalse(result.ok)
    def test_success_json_is_parsed(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"ok": true, "final": "quiet"}\n',
            stderr="",
        )
        result = ProfileClient._parse_result(completed)
        self.assertTrue(result.ok)
        self.assertEqual(result.final_profile, "quiet")

    def test_cancelled_auth_is_reported(self) -> None:
        completed = subprocess.CompletedProcess(args=[], returncode=126, stdout="", stderr="")
        result = ProfileClient._parse_result(completed)
        self.assertFalse(result.ok)
        self.assertIn("hủy", result.message)


if __name__ == "__main__":
    unittest.main()

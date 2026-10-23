"""Offline guard checks for the PPD Performance integration runner."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "power_profiles_performance_e2e_runner",
    Path(__file__).resolve().parents[1] / "research/power_profiles_performance_e2e_runner.py",
)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class PowerProfilesPerformanceE2ERunnerTests(unittest.TestCase):
    def test_requires_exact_confirmation_and_desktop_user(self) -> None:
        self.assertEqual(runner.main([]), 64)
        self.assertEqual(runner.main(["--wrong"]), 64)

    def test_scope_matches_the_app_ppd_path_and_has_rollback(self) -> None:
        source = Path(runner.__file__).read_text(encoding="utf-8")
        self.assertEqual(runner.CONFIRM_FLAG, "--confirm-x17r1-performance-ppd-e2e")
        self.assertEqual(runner.VERIFICATION_DELAYS, (0.0, 0.4, 0.6, 1.0))
        self.assertIn('set_ppd(TARGET)', source)
        self.assertIn('set_ppd(BASELINE)', source)
        self.assertIn(
            'if current["daemon"] != TARGET or current["platform"] != TARGET',
            source,
        )
        self.assertIn("watchdog-fired", source)
        self.assertNotIn('command("pkexec"', source)
        self.assertNotIn("insmod", source)
        self.assertNotIn("modprobe", source)
        self.assertNotIn("fan_boost", source)
        self.assertNotIn("pwm", source.lower())


if __name__ == "__main__":
    unittest.main()

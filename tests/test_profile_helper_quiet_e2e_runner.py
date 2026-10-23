"""Offline guard checks for the installed-helper Quiet integration runner."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "profile_helper_quiet_e2e_runner",
    Path(__file__).resolve().parents[1] / "research/profile_helper_quiet_e2e_runner.py",
)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class ProfileHelperQuietE2ERunnerTests(unittest.TestCase):
    def test_requires_its_own_exact_confirmation(self) -> None:
        self.assertEqual(runner.main([]), 64)
        self.assertEqual(runner.main(["--wrong"]), 64)

    def test_scope_uses_only_the_installed_profile_helper(self) -> None:
        source = Path(runner.__file__).read_text(encoding="utf-8")
        self.assertEqual(
            runner.CONFIRM_FLAG, "--confirm-x17r1-profile-helper-quiet-e2e"
        )
        self.assertEqual(runner.HELPER, Path("/usr/libexec/awcc-profile-helper"))
        self.assertEqual(runner.MAX_BASELINE_TEMP, 60.0)
        self.assertIn("max(temps.values()) > MAX_BASELINE_TEMP", source)
        self.assertIn('request(base.TARGET_PROFILE)', source)
        self.assertIn('request("balanced")', source)
        self.assertIn("helper_metadata_is_safe()", source)
        self.assertIn("if preflight_ok:", source)
        self.assertNotIn("insmod", source)
        self.assertNotIn("modprobe", source)
        self.assertNotIn("pwm", source.lower())
        self.assertNotIn("fan_boost", source)
        self.assertNotIn("set_service(False)", source)


if __name__ == "__main__":
    unittest.main()

"""Offline safety checks for the Quiet-with-PPD diagnostic runner."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "quiet_with_ppd_runner",
    Path(__file__).resolve().parents[1] / "research/quiet_with_ppd_profile_test_runner.py",
)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class QuietWithPpdRunnerTests(unittest.TestCase):
    def test_requires_its_own_exact_confirmation(self) -> None:
        self.assertEqual(runner.main([]), 64)
        self.assertEqual(runner.main(["--wrong"]), 64)

    def test_scope_keeps_ppd_active_and_never_changes_modules(self) -> None:
        source = Path(runner.__file__).read_text(encoding="utf-8")
        self.assertEqual(runner.CONFIRM_FLAG, "--confirm-x17r1-quiet-with-ppd-test")
        self.assertEqual(runner.STOCK_SRCVERSION, "28A4134FBF8432C66D7C668")
        self.assertNotIn("set_service(False)", source)
        self.assertNotIn('"stop", SERVICE', source)
        self.assertNotIn("insmod", source)
        self.assertNotIn("modprobe", source)
        self.assertNotIn("load_stock_module", source)
        self.assertEqual(source.count('write_text(f"{base.TARGET_PROFILE}\\n"'), 1)
        self.assertIn("not base.service_active()", source)
        self.assertIn("awccd_isolated()", source)
        self.assertIn("if preflight_ok:", source)


if __name__ == "__main__":
    unittest.main()

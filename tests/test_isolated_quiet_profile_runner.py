"""Offline guards for the post-awccd stock-driver Quiet diagnostic."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    "isolated_quiet_runner",
    Path(__file__).resolve().parents[1] / "research/isolated_quiet_profile_test_runner.py",
)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class IsolatedQuietRunnerTests(unittest.TestCase):
    def test_requires_its_own_exact_confirmation(self) -> None:
        self.assertEqual(runner.main([]), 64)
        self.assertEqual(runner.main(["--wrong"]), 64)

    def test_scope_remains_one_stock_driver_quiet_write(self) -> None:
        source = Path(runner.__file__).read_text(encoding="utf-8")
        self.assertEqual(runner.CONFIRM_FLAG, "--confirm-x17r1-isolated-quiet-stock-test")
        self.assertEqual(runner.STOCK_SRCVERSION, "28A4134FBF8432C66D7C668")
        self.assertIn("awccd_isolated()", source)
        self.assertNotIn("insmod", source)
        self.assertNotIn("modprobe", source)
        self.assertNotIn("load_stock_module", source)
        self.assertEqual(source.count("write_text(f\"{base.TARGET_PROFILE}\\n\""), 1)
        self.assertIn("if preflight_ok:", source)
        self.assertIn("preflight failed before any mutation", source)


if __name__ == "__main__":
    unittest.main()

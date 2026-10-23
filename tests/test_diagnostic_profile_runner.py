"""Offline safety checks for the one-shot ordinary-profile diagnostic runner."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "profile_diagnostic",
    Path(__file__).resolve().parents[1] / "research/diagnostic_profile_test_runner.py",
)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class DiagnosticProfileRunnerSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.paths = patch.multiple(
            runner,
            MUTATION_LOCK=root / "lock",
            EXPIRED=root / "expired",
            CANCEL=root / "cancel",
            DEADLINE=time.monotonic() + 10,
            CANDIDATE_COPY=root / "candidate.ko",
        )
        self.paths.start()
        self.addCleanup(self.paths.stop)
        self.addCleanup(self.temp.cleanup)

    def test_watchdog_expiry_blocks_future_test_writes(self) -> None:
        runner.EXPIRED.touch()
        with self.assertRaises(RuntimeError), runner.test_mutation():
            self.fail("No test write may start after watchdog expiry.")

    def test_deadline_blocks_future_test_writes(self) -> None:
        with patch.object(runner, "DEADLINE", time.monotonic() - 1):
            with self.assertRaises(RuntimeError), runner.test_mutation():
                self.fail("No test write may start after the deadline.")

    def test_candidate_load_uses_a_root_staged_copy_with_gmode_off(self) -> None:
        with patch.object(runner, "unload_module") as unload, patch.object(runner, "command") as command, \
             patch.object(runner, "read", return_value=runner.EXPECTED_SRCVERSION):
            runner.load_diagnostic_module()
        unload.assert_called_once_with()
        self.assertEqual(command.call_args.args[:2], ("insmod", str(runner.CANDIDATE_COPY)))
        self.assertIn("force_gmode=0", command.call_args.args)
        self.assertNotIn(str(runner.CANDIDATE), command.call_args.args)

    def test_stock_restore_explicitly_disables_gmode(self) -> None:
        with patch.object(runner, "unload_module") as unload, patch.object(runner, "command") as command:
            runner.load_stock_module()
        unload.assert_called_once_with()
        self.assertEqual(command.call_args.args[:2], ("modprobe", runner.MODULE))
        self.assertIn("force_gmode=0", command.call_args.args)

    def test_diagnostic_scope_is_quiet_profile_only(self) -> None:
        self.assertEqual(runner.TARGET_PROFILE, "quiet")
        self.assertEqual(runner.SAMPLE_COUNT, 10)
        self.assertEqual(runner.SAMPLE_INTERVAL, 0.25)


if __name__ == "__main__":
    unittest.main()

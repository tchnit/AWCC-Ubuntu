"""Offline checks only; never call sysfs writes, modprobe or systemctl."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "gmode_runner", Path(__file__).resolve().parents[1] / "research/gmode_profile_test_runner.py"
)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class GmodeRunnerSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.paths = patch.multiple(
            runner, MUTATION_LOCK=root / "lock", EXPIRED=root / "expired",
            CANCEL=root / "cancel", DEADLINE=time.monotonic() + 10,
        )
        self.paths.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.paths.stop)

    def test_allows_mutation_before_deadline(self) -> None:
        with runner.test_mutation():
            pass

    def test_expired_watchdog_blocks_any_later_test_write(self) -> None:
        runner.EXPIRED.touch()
        with self.assertRaises(RuntimeError), runner.test_mutation():
            self.fail("Should not enter a test mutation after watchdog restore.")

    def test_deadline_blocks_write_even_before_watchdog_gets_lock(self) -> None:
        with patch.object(runner, "DEADLINE", time.monotonic() - 1):
            with self.assertRaises(RuntimeError), runner.test_mutation():
                self.fail("Should not enter an overdue mutation.")

    def test_cancel_watchdog_only_after_verified_restore(self) -> None:
        with patch.object(runner, "restore_locked", return_value=False):
            self.assertFalse(runner.restore())
        self.assertFalse(runner.CANCEL.exists())
        with patch.object(runner, "restore_locked", return_value=True):
            self.assertTrue(runner.restore())
        self.assertTrue(runner.CANCEL.exists())

    def test_restore_explicitly_disables_force_gmode(self) -> None:
        with patch.object(runner, "command") as command:
            runner.load_module(False)
        self.assertEqual(command.call_args.args[-1], "force_gmode=0")

    def test_test_explicitly_enables_force_gmode(self) -> None:
        with patch.object(runner, "command") as command:
            runner.load_module(True)
        self.assertEqual(command.call_args.args[-1], "force_gmode=1")


if __name__ == "__main__":
    unittest.main()

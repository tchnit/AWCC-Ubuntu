import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


PATH = Path(__file__).resolve().parents[1] / "research/app_profile_write_e2e_runner.py"
spec = importlib.util.spec_from_file_location("app_profile_write_e2e_runner", PATH)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class InstalledAppRunnerTests(unittest.TestCase):
    def test_no_authorization_flag_never_initializes_or_writes(self):
        with patch.object(runner.safety, "initialize_state") as initialize:
            self.assertEqual(runner.main([]), 64)
            initialize.assert_not_called()

    def test_runner_refuses_root_parent(self):
        with patch.object(runner.os, "geteuid", return_value=0), patch.object(runner.safety, "initialize_state") as initialize:
            with self.assertRaises(RuntimeError):
                runner.main([runner.CONFIRM])
            initialize.assert_not_called()

    def test_missing_gpu_or_ac_or_conflict_blocks_mutation(self):
        safe = dict(temperatures={"CPU": 40, "GPU": 40}, ac_online=True, awccd_socket=False)
        for overrides in (dict(temperatures={"CPU": 40}), dict(ac_online=False), dict(awccd_socket=True), dict(temperatures={"CPU": 90, "GPU": 40})):
            with self.subTest(overrides=overrides), patch.object(runner, "sample", return_value=safe | overrides):
                with self.assertRaises(RuntimeError):
                    runner.guard()

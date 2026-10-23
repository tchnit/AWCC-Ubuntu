import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "research"


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class RemainingProfileGuardTests(unittest.TestCase):
    def test_root_probe_requires_exact_confirmation_and_narrow_target(self):
        probe = module("unverified_profile_probe")
        with patch.object(probe.os, "geteuid", return_value=0), patch.object(probe, "HardwareBackend") as backend:
            for args in ([], [probe.CONFIRM], [probe.CONFIRM, "performance"], [probe.CONFIRM, "custom", "extra"]):
                self.assertEqual(probe.main(args), 64)
            backend.assert_not_called()

    def test_guardian_requires_confirmation_and_nonroot(self):
        runner = module("unlock_profile_validation")
        with patch.object(runner.base.safety, "initialize_state") as initialize:
            self.assertEqual(runner.main([]), 64)
            with patch.object(runner.os, "geteuid", return_value=0):
                self.assertEqual(runner.main([runner.CONFIRM]), 64)
            initialize.assert_not_called()

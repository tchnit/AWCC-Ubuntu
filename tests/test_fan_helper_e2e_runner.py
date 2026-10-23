import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("fan_e2e_runner", Path(__file__).resolve().parents[1]/"research/fan_helper_e2e.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class InstalledFanE2ERunnerTests(unittest.TestCase):
    def test_explicit_confirmation_and_nonroot_are_required_before_work(self):
        with patch.object(runner.subprocess,"Popen") as start:
            self.assertEqual(runner.main([]),64)
            with patch.object(runner.os,"geteuid",return_value=0):
                self.assertEqual(runner.main([runner.CONFIRM,"--channel","1","--end","stop","--run","1"]),64)
            start.assert_not_called()

    def test_stage_evaluator_preserves_direction_stability_and_sample_count_gates(self):
        self.assertTrue(runner.assess({"A1":[3300]*15,"B":[4100]*15,"A2":[3300]*15})["responsive"])
        for phases in ({"A1":[3300]*15,"B":[3300]*15,"A2":[3300]*15},
                       {"A1":[3300]*15,"B":[4100]*15,"A2":[3300]*2},
                       {"A1":[3300]*11+[4500,4200,3800,3300],"B":[4100]*15,"A2":[3300]*15}):
            self.assertFalse(runner.assess(phases)["responsive"])

    def test_request_requires_matching_channel_raw_and_full_levels_ack(self):
        conn = runner.Connection(Mock(),Mock())
        conn.send = Mock()
        conn.wait_for = Mock()
        conn.messages = [{"event":"applied","seq":1,"channel":3,"raw":64,"levels":{"1":100,"2":100,"3":64,"4":100}}]
        conn.request(1,3,64)
        conn.send.assert_called_once_with({"op":"set","seq":1,"channel":3,"raw":64})
        with self.assertRaises(RuntimeError):
            conn.request(1,2,64)

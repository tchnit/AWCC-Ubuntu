from __future__ import annotations

import unittest
import subprocess
from unittest.mock import patch
from awcc_linux import power_profiles as module

from awcc_linux.power_profiles import (
    DAEMON_TO_PLATFORM,
    PLATFORM_TO_DAEMON,
    PowerProfilesState,
    profile_observations_are_stable,
    profile_routes_are_stable,
)


class PowerProfilesStateTests(unittest.TestCase):
    def test_profile_mapping(self) -> None:
        self.assertEqual(PLATFORM_TO_DAEMON["low-power"], "power-saver")
        self.assertEqual(DAEMON_TO_PLATFORM["power-saver"], "low-power")

    def test_performance_degradation_warns_but_does_not_block_request(self) -> None:
        state = PowerProfilesState(
            True,
            "balanced",
            ("power-saver", "balanced", "performance"),
            "high-operating-temperature",
        )
        self.assertIsNone(state.block_reason("performance"))
        self.assertIn("high-operating-temperature", state.warning("performance") or "")
        self.assertIsNone(state.block_reason("balanced"))

    def test_non_daemon_profile_is_not_claimed(self) -> None:
        state = PowerProfilesState(True, "balanced", ("balanced",), "")
        self.assertFalse(state.supports_platform_profile("balanced-performance"))
        self.assertIn("không quản lý", state.block_reason("balanced-performance") or "")

    def test_timed_readbacks_reject_delayed_rollback(self) -> None:
        self.assertFalse(
            profile_observations_are_stable(
                "power-saver",
                ("power-saver", "power-saver", "balanced", "balanced"),
            )
        )

    def test_timed_readbacks_accept_only_stable_target(self) -> None:
        self.assertTrue(
            profile_observations_are_stable(
                "balanced", ("balanced", "balanced", "balanced", "balanced")
            )
        )

    def test_ppd_success_requires_matching_alienware_platform_profile(self) -> None:
        self.assertTrue(
            profile_routes_are_stable(
                "performance",
                "performance",
                ("performance",) * 4,
                ("performance",) * 4,
            )
        )
        self.assertFalse(profile_routes_are_stable("performance", "performance", ("performance",) * 4, ("balanced",) * 4))

    def test_incomplete_observations_are_not_success(self):
        self.assertFalse(profile_routes_are_stable("performance", "performance", ("performance",), ("performance",)))


class InlineThread:
    def __init__(self, target, **kwargs):
        self.target = target
    def start(self):
        self.target()


class PowerProfileTransactionTests(unittest.TestCase):
    def run_request(self, fail_get=None, fail_restore=False, timeout_set=False, initial="balanced", initial_platform=None, fail_quiet_restore=False, restore_timeout_after_effect=False,target="performance",ppd_same_value_noop=False):
        client = object.__new__(module.PowerProfilesClient)
        client.busy = False
        client.state = PowerProfilesState(True, "balanced", ("power-saver", "balanced", "performance"))
        platform = initial_platform or initial
        active, reads = initial, 0
        calls, queued = [], []
        def command(args, **kwargs):
            nonlocal platform, active, reads
            calls.append(tuple(args))
            if args[1] == "set":
                if fail_restore and args[-1] == initial:
                    return subprocess.CompletedProcess(args, 1, "", "restore rejected")
                if ppd_same_value_noop and args[-1] == active:
                    return subprocess.CompletedProcess(args,0,"","")
                active = args[-1]
                platform = module.DAEMON_TO_PLATFORM[active]
                if restore_timeout_after_effect and args[-1] == initial:
                    raise subprocess.TimeoutExpired(args, 20)
                if timeout_set and args[-1] == "performance":
                    raise subprocess.TimeoutExpired(args, 20)
                return subprocess.CompletedProcess(args, 0, "", "")
            reads += 1
            if reads == fail_get:
                return subprocess.CompletedProcess(args, 1, "", "read failed")
            return subprocess.CompletedProcess(args, 0, active, "")
        client._platform_profile_reader = lambda: platform
        def quiet_restore():
            nonlocal platform, active
            if not fail_quiet_restore:
                platform = "quiet"
                active = initial
            return not fail_quiet_restore
        def helper_restore(profile):
            nonlocal platform,active
            platform=profile
            active= "balanced" if profile=="balanced" else initial
            return True
        with patch.object(module.subprocess, "run", command), patch.object(module.time, "sleep"), patch.object(module.threading, "Thread", InlineThread), patch.object(module.GLib, "idle_add", side_effect=lambda *args: queued.append(args)), patch.object(module, "helper_payload_reason", return_value=None), patch.object(module, "_restore_quiet", quiet_restore),patch.object(module,"_restore_helper_profile",helper_restore):
            client.set_platform_profile(target, lambda result: None)
        return queued[0][2], calls

    def test_complete_window_succeeds_without_restore(self):
        result, calls = self.run_request()
        self.assertTrue(result.ok)
        self.assertEqual(sum(call[1] == "get" for call in calls), 5)
        self.assertEqual(result.final_profile, "performance")
        self.assertNotIn(("powerprofilesctl", "set", "balanced"), calls)

    def test_read_failure_after_first_sample_restores_live_baseline(self):
        result, calls = self.run_request(fail_get=3)
        self.assertFalse(result.ok)
        self.assertEqual(result.final_profile, "balanced")
        self.assertIn("Đã khôi phục", result.message)
        self.assertIn(("powerprofilesctl", "set", "balanced"), calls)

    def test_timed_out_write_still_attempts_and_verifies_restore(self):
        result, calls = self.run_request(timeout_set=True)
        self.assertFalse(result.ok)
        self.assertEqual(result.final_profile, "balanced")

    def test_failed_restore_is_not_reported_as_restored(self):
        result, calls = self.run_request(fail_get=3, fail_restore=True)
        self.assertFalse(result.ok)
        self.assertEqual(result.final_profile, "performance")
        self.assertIn("Không xác minh", result.message)

    def test_restore_timeout_still_verifies_actual_completed_restore(self):
        result, calls = self.run_request(fail_get=3, restore_timeout_after_effect=True)
        self.assertFalse(result.ok)
        self.assertEqual(result.final_profile, "balanced")
        self.assertIn("Đã khôi phục", result.message)

    def test_initial_read_error_does_not_write(self):
        result, calls = self.run_request(fail_get=1)
        self.assertFalse(result.ok)
        self.assertFalse(any(call[1] == "set" for call in calls))

    def test_unrecoverable_baseline_does_not_write(self):
        result, calls = self.run_request(initial_platform="unknown-firmware-profile")
        self.assertFalse(result.ok)
        self.assertFalse(any(call[1] == "set" for call in calls))

    def test_quiet_baseline_is_restored_after_ppd_failure(self):
        result, calls = self.run_request(initial_platform="quiet", fail_get=3)
        self.assertFalse(result.ok)
        self.assertEqual(result.final_profile, "quiet")
        self.assertIn("Đã khôi phục quiet", result.message)

    def test_cancelled_quiet_restore_reports_actual_profile(self):
        result, calls = self.run_request(initial_platform="quiet", fail_get=3, fail_quiet_restore=True)
        self.assertFalse(result.ok)
        self.assertEqual(result.final_profile, "balanced")
        self.assertIn("Không xác minh", result.message)

    def test_quiet_alias_restores_now_verified_cpu_policy_before_thermal_helper(self):
        result, calls = self.run_request(initial="power-saver", initial_platform="quiet", fail_get=3)
        self.assertFalse(result.ok)
        self.assertEqual(result.final_profile, "quiet")
        self.assertIn("Đã khôi phục quiet", result.message)
        self.assertIn(("powerprofilesctl", "set", "power-saver"), calls)

    def test_balanced_plus_baseline_recovers_through_helper(self):
        result,calls=self.run_request(initial_platform="balanced-performance",fail_get=3)
        self.assertFalse(result.ok)
        self.assertEqual(result.final_profile,"balanced-performance")
        self.assertIn("Đã khôi phục",result.message)

    def test_custom_baseline_recovers_through_helper(self):
        result,calls=self.run_request(initial="power-saver",initial_platform="custom",fail_get=3)
        self.assertFalse(result.ok)
        self.assertEqual(result.final_profile,"custom")
        self.assertIn(("powerprofilesctl","set","power-saver"),calls)

    def test_same_value_ppd_balanced_plus_to_balanced_uses_verified_helper_bridge(self):
        result,calls=self.run_request(initial_platform="balanced-performance",target="balanced",ppd_same_value_noop=True)
        self.assertTrue(result.ok)
        self.assertEqual(result.final_profile,"balanced")

    def test_same_value_low_power_from_custom_uses_balanced_ppd_bridge(self):
        result,calls=self.run_request(initial="power-saver",initial_platform="custom",target="low-power",ppd_same_value_noop=True)
        self.assertTrue(result.ok)
        self.assertEqual(result.final_profile,"low-power")
        self.assertIn(("powerprofilesctl","set","balanced"),calls)

    def test_ppd_success_rejects_missing_platform_readback(self) -> None:
        self.assertFalse(
            profile_routes_are_stable(
                "performance",
                "performance",
                ("performance",),
                (None,),
            )
        )


if __name__ == "__main__":
    unittest.main()

"""All ports are fake; these tests never read or mutate host fan hardware."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from awcc_linux.fan_policy import FanControlError, check_levels, check_snapshot
from awcc_linux.fan_session import FanSession
from awcc_linux.models import AwccFan, CapabilityReport, ControlState, Fan, ProfileState, SystemSnapshot, Temperature


def snapshot(profile="balanced", boosts=None):
    boosts = boosts or dict.fromkeys(range(1, 5), 0)
    return SystemSnapshot(
        datetime.now(timezone.utc), "Alienware x17 R1", "1.27.0", "7.0.0-38-generic",
        ProfileState(profile, ("balanced", "performance", "low-power", "custom"), "alienware-wmi"),
        tuple(Fan(i, "Fan", 3000, pwm_enable=2) for i in range(1, 5)),
        tuple(AwccFan(i, "Fan", 3000, 0, 5000, boosts[i]) for i in range(1, 5)),
        (Temperature(1, "CPU", 43, "AWCC WMI"), Temperature(1, "GPU", 39, "NVIDIA NVML")),
        CapabilityReport(True, True, False, ControlState.BIOS_AUTO, awcc_fan_boost=True),
    )


class Clock:
    value = 100.0
    def __call__(self):
        return self.value


class FakePort:
    def __init__(self, clock):
        self.clock = clock
        self.state = snapshot()
        self.mode = "balanced"
        self.ac_on = True
        self.original = None
        self.events = []
        self.restore_ok = True
        self.ignore_write = False

    def snapshot(self):
        return replace(self.state, captured_at=datetime.now(timezone.utc))

    def ac(self):
        return self.ac_on

    def ensure_identity(self):
        self.events.append(("identity",))

    def daemon(self):
        return self.mode

    def arm_recovery(self, original):
        self.original = original
        self.events.append(("guardian", original))

    def set_cooling(self):
        assert self.original is not None
        self.events.append(("cooling",))
        self.mode = "power-saver"
        self.state = replace(self.state, profile=replace(self.state.profile, current="low-power"))

    def enter_custom(self):
        self.events.append(("custom",))
        self.state = replace(self.state, profile=replace(self.state.profile, current="custom"))

    def set_boost(self, channel, raw):
        assert self.original is not None
        self.events.append(("set", channel, raw))
        if not self.ignore_write:
            self.state = replace(self.state, awcc_fans=tuple(replace(f, boost=raw) if f.channel == channel else f for f in self.state.awcc_fans))

    def heartbeat(self):
        self.events.append(("heartbeat",))

    def sleep(self, seconds):
        self.clock.value += seconds

    def recover(self):
        self.events.append(("recover",))
        if self.restore_ok:
            self.state = snapshot(self.original)
            self.mode = self.original
        return self.restore_ok


class FanPolicyTests(unittest.TestCase):
    def test_correct_native_interface_does_not_require_smm_manual(self):
        self.assertEqual(check_snapshot(snapshot(), True, starting=True), 43)

    def test_model_bios_kernel_provider_and_controller_are_gated(self):
        state = snapshot()
        for changed in (
            replace(state, model="other"), replace(state, bios_version="1.28.0"),
            replace(state, kernel="new"), replace(state, profile=replace(state.profile, provider="other")),
            replace(state, capabilities=replace(state.capabilities, external_awccd_controller=True)),
        ):
            with self.subTest(changed=changed), self.assertRaises(FanControlError):
                check_snapshot(changed, True)
        with self.assertRaises(FanControlError):
            check_snapshot(state, False)

    def test_snapshot_must_be_fresh_and_timezone_aware(self):
        state = snapshot()
        for captured in (state.captured_at - timedelta(seconds=4), state.captured_at + timedelta(seconds=2), state.captured_at.replace(tzinfo=None)):
            with self.assertRaises(FanControlError):
                check_snapshot(replace(state, captured_at=captured), True)

    def test_sensor_sources_duplicates_and_nonfinite_values_are_rejected(self):
        state = snapshot()
        invalid = (state.temperatures[:1], state.temperatures + state.temperatures[:1],
                   (state.temperatures[0], Temperature(1, "GPU", 40, "AWCC WMI")))
        for value in (None, float("nan"), float("inf"), 9, 70, True):
            invalid += ((replace(state.temperatures[0], celsius=value), state.temperatures[1]),)
        for sensors in invalid:
            with self.subTest(sensors=sensors), self.assertRaises(FanControlError):
                check_snapshot(replace(state, temperatures=sensors), True)

    def test_cpu_start_above_50_is_allowed_but_absolute_ceiling_remains(self):
        state = snapshot()
        for value in (50, 50.1, 53, 69.9):
            with self.subTest(value=value):
                hot = replace(state, temperatures=(replace(state.temperatures[0], celsius=value), state.temperatures[1]))
                self.assertEqual(check_snapshot(hot, True, starting=True), value)
        for value in (70, 80, None, float("nan"), float("inf"), True):
            with self.subTest(value=value), self.assertRaises(FanControlError):
                check_snapshot(replace(state, temperatures=(replace(state.temperatures[0], celsius=value), state.temperatures[1])), True, starting=True)

    def test_non_cpu_start_and_temperature_rise_limits_are_not_relaxed(self):
        state = snapshot()
        for label in ("GPU", "SODIMM", "Other"):
            sensor = Temperature(1, label, 50, "NVIDIA NVML" if label == "GPU" else "dell_smm")
            base = state.temperatures[:1] if label == "GPU" else state.temperatures
            check_snapshot(replace(state, temperatures=base + (sensor,)), True, starting=True)
            with self.subTest(label=label), self.assertRaises(FanControlError):
                check_snapshot(replace(state, temperatures=base + (replace(sensor, celsius=50.1),)), True, starting=True)
        with self.assertRaises(FanControlError):
            check_snapshot(state, True, baseline_hot=33)

    def test_topology_bad_rpm_stopped_fan_and_boost_mismatch_abort(self):
        state = snapshot()
        for fans in (state.awcc_fans[:3], state.awcc_fans[:3] + state.awcc_fans[:1],
                     (replace(state.awcc_fans[0], rpm=None),) + state.awcc_fans[1:],
                     (replace(state.awcc_fans[0], rpm=0),) + state.awcc_fans[1:]):
            with self.assertRaises(FanControlError):
                check_snapshot(replace(state, awcc_fans=fans), True, require_spinning=True)
        with self.assertRaises(FanControlError):
            check_snapshot(state, True, expected_profile="custom")
        with self.assertRaises(FanControlError):
            check_snapshot(state, True, levels=dict.fromkeys(range(1, 5), 100))

    def test_smm_state_is_observed_not_taken_over(self):
        state = snapshot()
        for fans in ((), (replace(state.fans[0], pwm_enable=1),) + state.fans[1:]):
            with self.assertRaises(FanControlError):
                check_snapshot(replace(state, fans=fans), True)

    def test_full_raw_abi_range_and_one_changed_channel(self):
        check_levels(dict.fromkeys(range(1, 5), 100))
        for channel in range(1, 5):
            for raw in range(256):
                check_levels({i: raw if i == channel else 100 for i in range(1, 5)})
        for levels in ({1: 64, 2: 64, 3: 100, 4: 100}, {1: 100},
                       {1: 0, 2: 255, 3: 100, 4: 100},
                       {1: True, 2: 100, 3: 100, 4: 100},
                       {1: -1, 2: 100, 3: 100, 4: 100}, {1: 256, 2: 100, 3: 100, 4: 100}):
            with self.assertRaises(FanControlError):
                check_levels(levels)


class FanSessionTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.port = FakePort(self.clock)
        self.session = FanSession(self.port, self.clock)

    def start(self):
        self.session.start()
        self.assertTrue(self.session.active)

    def test_guardian_precedes_every_mutation_and_initial_levels_are_100(self):
        self.start()
        actions = [e for e in self.port.events if e[0] != "identity"]
        self.assertEqual(actions[:7], [("guardian", "balanced"), ("cooling",), ("custom",)] + [("set", i, 100) for i in range(1, 5)])
        self.assertEqual(self.session.deadline, 160)

    def test_preflight_failure_has_no_guardian_or_mutation(self):
        self.port.ac_on = False
        with self.assertRaises(FanControlError):
            self.session.start()
        self.assertFalse(self.session.armed)
        self.assertEqual(self.port.events, [("identity",)])

    def test_warm_cpu_session_starts_and_restores_at_absolute_or_rise_limit(self):
        for initial, final in ((53, 63), (65, 70)):
            with self.subTest(initial=initial, final=final):
                clock = Clock()
                port = FakePort(clock)
                port.state = replace(port.state, temperatures=(replace(port.state.temperatures[0], celsius=initial), port.state.temperatures[1]))
                session = FanSession(port, clock)
                session.start()
                self.assertTrue(session.active)
                port.state = replace(port.state, temperatures=(replace(port.state.temperatures[0], celsius=final), port.state.temperatures[1]))
                with self.assertRaises(FanControlError):
                    session.tick()
                self.assertTrue(session.restored)
                self.assertFalse(session.active)

    def test_warm_cpu_does_not_hide_gpu_rise(self):
        self.port.state = replace(self.port.state, temperatures=(replace(self.port.state.temperatures[0], celsius=60), self.port.state.temperatures[1]))
        self.start()
        self.port.state = replace(self.port.state, temperatures=(self.port.state.temperatures[0], replace(self.port.state.temperatures[1], celsius=49)))
        with self.assertRaises(FanControlError):
            self.session.tick()
        self.assertTrue(self.session.restored)

    def test_unrecoverable_pair_or_nonzero_baseline_is_rejected(self):
        for profile, mode, boosts in (("quiet", "balanced", None), ("balanced", "power-saver", None),
                                       ("balanced", "balanced", dict.fromkeys(range(1, 5), 100))):
            self.port.state = snapshot(profile, boosts)
            self.port.mode = mode
            with self.assertRaises(FanControlError):
                self.session.start()
        self.assertFalse(self.session.armed)

    def test_armed_custom_baseline_has_standard_ppd_recovery_target(self):
        self.port.state = snapshot("custom")
        self.port.mode = "performance"
        self.start()
        self.session.stop()
        self.assertEqual(self.port.state.profile.current, "performance")

    def test_start_failure_after_mutation_recovers(self):
        def fail():
            raise OSError("blocked firmware call")
        self.port.enter_custom = fail
        with self.assertRaises(OSError):
            self.session.start()
        self.assertTrue(self.session.restored)
        self.assertIn(("recover",), self.port.events)

    def test_startup_that_exhausts_lease_cannot_become_ready(self):
        original = self.port.enter_custom
        def slow():
            original()
            self.clock.value += 60
        self.port.enter_custom = slow
        with self.assertRaises(FanControlError):
            self.session.start()
        self.assertFalse(self.session.active)
        self.assertTrue(self.session.restored)

    def test_set_boost_reads_back_and_suppresses_identical_requests(self):
        self.start()
        self.session.set_boost(3, 64)
        self.assertEqual(self.session.levels[3], 64)
        count = self.port.events.count(("set", 3, 64))
        self.session.set_boost(3, 64)
        self.assertEqual(self.port.events.count(("set", 3, 64)), count)

    def test_invalid_values_second_changed_channel_and_fast_writes_are_blocked(self):
        self.start()
        self.session.set_boost(2, 64)
        count = len([e for e in self.port.events if e[0] == "set"])
        for channel, raw in ((1, 64), (2, -1), (2, 256), (True, 100), (5, 100), (2, 100)):
            with self.subTest(channel=channel, raw=raw), self.assertRaises(FanControlError):
                self.session.set_boost(channel, raw)
        self.assertEqual(len([e for e in self.port.events if e[0] == "set"]), count)
        self.clock.value += 2
        self.session.set_boost(2, 100)

    def test_full_range_requests_are_not_silently_clamped_in_fake_port(self):
        for raw in range(256):
            clock = Clock()
            port = FakePort(clock)
            session = FanSession(port, clock)
            session.start()
            session.set_boost(3,raw)
            self.assertEqual(session.levels[3],raw)
            self.assertEqual(port.state.awcc_fans[2].boost,raw)
            session.stop()

    def test_raw_zero_permission_does_not_disable_stopped_fan_guard(self):
        self.start()
        original = self.port.set_boost
        def simulate_stopped_fan(channel,raw):
            original(channel,raw)
            self.port.state = replace(self.port.state,awcc_fans=tuple(replace(f,rpm=0) if f.channel==channel else f for f in self.port.state.awcc_fans))
        self.port.set_boost = simulate_stopped_fan
        with self.assertRaises(FanControlError):
            self.session.set_boost(3,0)
        self.assertTrue(self.session.restored)

    def test_write_readback_mismatch_restores_without_success(self):
        self.start()
        self.port.ignore_write = True
        with self.assertRaises(FanControlError):
            self.session.set_boost(4, 64)
        self.assertTrue(self.session.restored)
        self.assertFalse(self.session.active)

    def test_missing_heartbeat_stops_and_late_heartbeat_cannot_revive_lease(self):
        self.start()
        self.clock.value += 5
        with self.assertRaises(FanControlError):
            self.session.heartbeat()
        with self.assertRaises(FanControlError):
            self.session.tick()
        self.assertTrue(self.session.restored)

    def test_heartbeat_does_not_extend_absolute_deadline(self):
        self.start()
        for _ in range(14):
            self.clock.value += 4
            if self.clock() < self.session.deadline:
                self.session.heartbeat()
        with self.assertRaises(FanControlError):
            self.session.tick()
        self.assertTrue(self.session.restored)

    def test_hot_ac_loss_profile_and_ppd_changes_recover(self):
        for problem in ("ac", "temperature", "profile", "ppd"):
            clock = Clock()
            port = FakePort(clock)
            session = FanSession(port, clock)
            session.start()
            if problem == "ac":
                port.ac_on = False
            elif problem == "temperature":
                port.state = replace(port.state, temperatures=(Temperature(1, "CPU", 70, "AWCC WMI"), port.state.temperatures[1]))
            elif problem == "profile":
                port.state = replace(port.state, profile=replace(port.state.profile, current="balanced"))
            else:
                port.mode = "balanced"
            with self.subTest(problem=problem), self.assertRaises(FanControlError):
                session.tick()
            self.assertTrue(session.restored)

    def test_stop_is_idempotent_and_does_not_claim_failed_recovery(self):
        self.start()
        self.assertTrue(self.session.stop())
        self.assertTrue(self.session.stop())
        self.assertEqual(self.port.events.count(("recover",)), 1)
        other = FanSession(FakePort(Clock()), Clock())
        other.start()
        other.port.restore_ok = False
        self.assertFalse(other.stop())
        self.assertFalse(other.restored)

    def test_individual_gpu_rise_is_not_hidden_by_hotter_cpu_baseline(self):
        self.start()
        self.port.state = replace(self.port.state, temperatures=(self.port.state.temperatures[0],Temperature(1,"GPU",49,"NVIDIA NVML")))
        with self.assertRaises(FanControlError):
            self.session.tick()
        self.assertTrue(self.session.restored)

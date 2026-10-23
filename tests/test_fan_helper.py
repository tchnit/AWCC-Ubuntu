"""Protocol/root adapter checks with fake paths and mocked processes only."""
from contextlib import nullcontext
from pathlib import Path
import os
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from awcc_linux import fan_helper, fan_hardware
from awcc_linux.fan_policy import FanControlError
from test_fan_session import snapshot


class ExitGuardian(BaseException):
    pass


class FanProtocolTests(unittest.TestCase):
    def test_only_narrow_commands_are_accepted(self):
        for line in (b'{"op":"start"}', b'{"op":"heartbeat"}', b'{"op":"stop"}',
                     b'{"op":"set","channel":4,"raw":64,"seq":1}'):
            self.assertIsInstance(fan_helper.parse_command(line), dict)
        for line in (b'[]', b'null', b'{"op":"set","channel":true,"raw":64,"seq":1}',
                     b'{"op":"set","channel":1,"raw":256,"seq":1}',
                     b'{"op":"set","channel":5,"raw":100,"seq":1}',
                     b'{"op":"set","channel":1,"raw":100,"seq":true}',
                     b'{"op":"stop","path":"/sys"}', b'{"op":"stop","op":"start"}',
                     b'\xff', b' ' * 257):
            with self.subTest(line=line), self.assertRaises(FanControlError):
                fan_helper.parse_command(line)

    def test_protocol_accepts_every_raw_integer_without_clamping(self):
        for raw in range(256):
            line = ('{"op":"set","channel":3,"raw":%d,"seq":1}' % raw).encode()
            self.assertEqual(fan_helper.parse_command(line)["raw"],raw)

    def serve_bytes(self, data, session):
        reader, writer = os.pipe()
        try:
            os.write(writer, data)
            os.close(writer)
            writer = None
            with patch.object(fan_helper, "reply"):
                return fan_helper.serve(session, reader)
        finally:
            os.close(reader)
            if writer is not None:
                os.close(writer)

    def fake_session(self):
        session = Mock()
        session.levels = dict.fromkeys(range(1, 5), 100)
        session.deadline = 100
        session.clock.return_value = 50
        return session

    def test_no_start_handshake_or_explicit_stop_never_arms_hardware(self):
        for data in (b'', b'{"op":"stop"}\n'):
            session = self.fake_session()
            self.serve_bytes(data, session)
            session.start.assert_not_called()

    def test_explicit_start_then_set_and_stop_uses_only_requested_channel(self):
        session = self.fake_session()
        self.serve_bytes(b'{"op":"start"}\n{"op":"heartbeat"}\n{"op":"set","channel":3,"raw":64,"seq":1}\n{"op":"stop"}\n', session)
        session.start.assert_called_once()
        session.heartbeat.assert_called_once()
        session.set_boost.assert_called_once_with(3, 64)

    def test_replayed_request_cannot_repeat_a_write(self):
        session = self.fake_session()
        with self.assertRaises(FanControlError):
            self.serve_bytes(b'{"op":"start"}\n'+b'{"op":"set","channel":2,"raw":64,"seq":1}\n'*2, session)
        session.set_boost.assert_called_once_with(2, 64)

    def test_argument_root_and_deployment_gates_precede_port_creation(self):
        with patch.object(fan_hardware, "NativeFanPort") as port, patch.object(fan_helper, "reply"):
            for args in ([], ["set", "1", "64"], ["session", "--path", "/sys"]):
                self.assertEqual(fan_helper.main(args), 64)
            with patch.object(fan_helper.os, "geteuid", return_value=1000):
                self.assertEqual(fan_helper.main(["validation-session"]), 64)
            with patch.object(fan_helper.os, "geteuid", return_value=0), patch.object(fan_helper, "fan_deployment_reason", return_value="not validated"):
                self.assertEqual(fan_helper.main(["session"]), 77)
            with patch.object(fan_helper.os, "geteuid", return_value=0), patch.object(fan_helper, "fan_candidate_reason", return_value="missing candidate"):
                self.assertEqual(fan_helper.main(["validation-session"]), 77)
            port.assert_not_called()

    def test_server_exception_still_stops_and_waits_for_guardian(self):
        port = Mock()
        port.guardian = 456
        port.directory = Path("/unused-test-runtime")
        port.finish.return_value = True
        session = Mock(armed=True)
        session.stop.return_value = True
        with patch.object(fan_helper.os, "geteuid", return_value=0), patch.object(fan_helper.os, "umask"), patch.dict(os.environ), patch.object(fan_helper.signal, "signal"), patch.object(fan_helper, "fan_candidate_reason", return_value=None), patch.object(fan_hardware, "acquire_singleton", return_value=123), patch.object(fan_hardware, "NativeFanPort", return_value=port), patch.object(fan_helper, "FanSession", return_value=session), patch.object(fan_helper, "serve", side_effect=FanControlError("test disconnect")), patch.object(fan_helper.os, "close") as close, patch.object(fan_helper, "reply") as reply:
            self.assertEqual(fan_helper.main(["validation-session"]), 1)
        session.stop.assert_called_once()
        port.finish.assert_called_once()
        close.assert_called_once_with(123)
        self.assertTrue(reply.call_args.kwargs["restored"])
        self.assertIn("test disconnect", reply.call_args.kwargs["message"])


class NativeFanPortTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.port = object.__new__(fan_hardware.NativeFanPort)
        self.port.directory = self.port.hwmon = root
        self.port.profile = root / "profile"
        self.port.profile.write_text("custom")
        self.port.fence = root / "fenced"
        self.port.recovering = root / "recovering"
        self.port.verified = root / "verified"
        self.port.custom_deadline = root / "custom.deadline"
        self.port.heartbeat_deadline = root / "heartbeat.deadline"
        self.port.startup_deadline = root / "startup.deadline"
        self.port.startup_deadline.write_text(str(time.monotonic() + 1000))
        self.port.guardian = 456
        self.port.original = "performance"
        self.port.audit = Mock()
        self.port.locked = Mock(side_effect=lambda _: nullcontext())

    def test_boost_api_rejects_arbitrary_values_and_channels(self):
        for channel, raw in ((0, 100), (5, 64), (True, 100), (1, -1), (1, 256), (1, True)):
            with self.assertRaises(FanControlError):
                self.port.set_boost(channel, raw)
        self.assertFalse((self.port.hwmon / "fan1_boost").exists())

    def test_native_writer_preserves_all_raw_values_using_temporary_files_only(self):
        for raw in range(256):
            self.port.set_boost(2,raw)
            self.assertEqual((self.port.hwmon/"fan2_boost").read_text(),str(raw)+"\n")

    def test_write_fence_custom_only_and_recovery_zero_guards(self):
        self.port.fence.touch()
        with self.assertRaises(FanControlError):
            self.port.set_boost(1, 64)
        self.port.fence.unlink()
        self.port.profile.write_text("balanced")
        with self.assertRaises(FanControlError):
            self.port.set_boost(1, 64)
        self.port.profile.write_text("custom")
        with self.assertRaises(FanControlError):
            self.port._write(self.port.hwmon / "fan1_boost", 0, recovery=True)
        self.port.set_boost(1, 64)
        self.assertEqual((self.port.hwmon / "fan1_boost").read_text(), "64\n")

    def test_guardian_must_be_armed_before_write(self):
        self.port.guardian = None
        with self.assertRaises(FanControlError):
            self.port.set_boost(2, 100)

    def test_expired_lease_rejects_writes_and_ppd_but_allows_recovery(self):
        target = self.port.hwmon / "fan1_boost"
        self.port.command = Mock()
        self.port.custom_deadline.write_text("1")
        self.port.heartbeat_deadline.write_text("1")
        with self.assertRaises(FanControlError):
            self.port.set_boost(1, 64)
        self.assertFalse(target.exists())
        with self.assertRaises(FanControlError):
            self.port._set_daemon("power-saver")
        self.port.command.assert_not_called()
        with self.assertRaises(FanControlError):
            self.port.heartbeat()
        self.port._write(self.port.profile, "performance", recovery=True)
        self.port._write(target, 0, recovery=True)
        self.assertEqual(target.read_text(), "0\n")

    def test_startup_deadline_rejects_pre_custom_ppd_write(self):
        self.port.startup_deadline.write_text("1")
        self.port.command = Mock()
        with self.assertRaises(FanControlError):
            self.port._set_daemon("power-saver")
        self.port.command.assert_not_called()

    def test_ppd_request_needs_its_full_timeout_before_lease_expiry(self):
        self.port.startup_deadline.write_text(str(time.monotonic() + 10))
        self.port.command = Mock()
        with self.assertRaises(FanControlError):
            self.port._set_daemon("power-saver")
        self.port.command.assert_not_called()

    def test_slow_backend_timestamp_is_not_mistaken_for_fresh_telemetry(self):
        self.port.backend = Mock()
        self.port.backend.snapshot.return_value = snapshot()
        with patch.object(fan_hardware.time,"monotonic",side_effect=[100,104]):
            with self.assertRaises(FanControlError):
                self.port.snapshot()

    def test_recovery_bridges_ppd_restores_zero_then_verifies_actual_state(self):
        self.port._set_daemon = Mock()
        self.port._verify_pair = Mock(return_value=True)
        self.port._write = Mock()
        self.port.snapshot = Mock(return_value=snapshot("performance"))
        self.port.daemon = Mock(return_value="performance")
        with patch.object(fan_hardware.time, "sleep"):
            self.assertTrue(self.port.recover())
        self.assertEqual([call.args[0] for call in self.port._set_daemon.call_args_list], ["balanced", "performance"])
        self.assertEqual([(call.args[0].name, call.args[1]) for call in self.port._write.call_args_list], [(f"fan{i}_boost", 0) for i in range(1, 5)])
        self.assertEqual(self.port.snapshot.call_count, 4)
        self.assertTrue(self.port.verified.exists())
        self.assertTrue(self.port.recover())
        self.assertEqual(self.port.snapshot.call_count, 4)

    def test_failed_bridge_never_restores_zero_into_custom_or_cancels_guardian(self):
        self.port._set_daemon = Mock()
        self.port._verify_pair = Mock(return_value=False)
        self.port._write = Mock()
        self.assertFalse(self.port.recover())
        self.assertFalse(self.port.verified.exists())
        boosts = [call.args[1] for call in self.port._write.call_args_list if "boost" in call.args[0].name]
        self.assertEqual(boosts, [100]*4)

    def test_failing_restore_readback_is_not_reported_as_success(self):
        self.port._set_daemon = Mock()
        self.port._verify_pair = Mock(return_value=True)
        self.port._write = Mock()
        self.port.snapshot = Mock(return_value=snapshot("balanced"))
        self.port.daemon = Mock(return_value="performance")
        with patch.object(fan_hardware.time, "sleep"):
            self.assertFalse(self.port.recover())
        self.assertFalse(self.port.verified.exists())

    def test_deadline_publish_is_atomic(self):
        self.port.publish_deadline(self.port.custom_deadline, 123)
        self.assertEqual(self.port.custom_deadline.read_text(), "123")
        self.assertFalse(self.port.custom_deadline.with_suffix(".deadline.next").exists())

    def test_watchdog_fires_on_timeout_nan_heartbeat_and_parent_death(self):
        for problem in ("hard", "heartbeat", "nan", "parent"):
            self.port.custom_deadline.write_text("0" if problem == "hard" else "1000")
            self.port.heartbeat_deadline.write_text("nan" if problem == "nan" else "50" if problem == "heartbeat" else "1000")
            self.port.recover = Mock(return_value=True)
            with self.subTest(problem=problem), patch.object(fan_hardware.os, "setsid"), patch.object(fan_hardware.signal, "signal"), patch.object(fan_hardware.time, "monotonic", return_value=100), patch.object(fan_hardware.os, "getppid", return_value=321 if problem == "parent" else 123), patch.object(fan_hardware.os, "kill") as kill, patch.object(fan_hardware.os, "_exit", side_effect=ExitGuardian):
                with self.assertRaises(ExitGuardian):
                    self.port._watchdog(123)
            self.assertTrue(self.port.fence.exists())
            kill.assert_called_once_with(123, fan_hardware.signal.SIGTERM)
            self.port.recover.assert_called_once()

    def test_failed_parent_restore_requests_guardian_and_waits(self):
        self.port.audit_fd = 123
        with patch.object(fan_hardware.os, "waitpid") as wait, patch.object(fan_hardware.os, "close"):
            self.assertFalse(self.port.finish())
        self.assertEqual(self.port.custom_deadline.read_text(), "0")
        wait.assert_called_once_with(456, 0)

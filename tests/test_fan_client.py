from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from awcc_linux import fan_client, fan_integrity
from awcc_linux.fan_client import FanClient, FanClientState, parse_event


class FanClientTests(unittest.TestCase):
    def setUp(self):
        self.client = FanClient(dispatch=lambda fn, *args: fn(*args))
        self.addCleanup(self.client.close)

    def test_default_and_unavailable_client_never_spawns_helper(self):
        with patch.object(fan_client, "fan_deployment_reason", return_value="not validated"), patch.object(fan_client.subprocess, "Popen") as launch:
            self.assertFalse(self.client.start())
            self.assertFalse(self.client.set_boost(1, 64))
            self.assertFalse(self.client.state.running)
            launch.assert_not_called()

    def test_start_is_explicit_single_flight_and_not_automatic(self):
        with patch.object(fan_client, "fan_deployment_reason", return_value=None), patch.object(fan_client.threading, "Thread") as thread:
            thread.assert_not_called()
            self.assertTrue(self.client.start())
            self.assertFalse(self.client.start())
            self.assertTrue(self.client.state.running)
            self.assertFalse(self.client.state.ready)
            thread.return_value.start.assert_called_once()

    def test_set_only_queues_valid_change_after_ready_and_awaits_ack(self):
        self.client.state = FanClientState(running=True, ready=True)
        for channel, raw in ((0, 64), (5, 100), (True, 100), (1, -1), (1, 256), (1, True)):
            self.assertFalse(self.client.set_boost(channel, raw))
        self.assertFalse(self.client.set_boost(1, 100))
        self.assertTrue(self.client.set_boost(3, 64))
        self.assertTrue(self.client.state.pending)
        self.assertFalse(self.client.set_boost(4, 64))
        request = self.client.commands.get_nowait()
        self.assertEqual(request, {"op":"set", "channel":3, "raw":64, "seq":1})
        self.client._event({"event":"applied", "seq":1, "channel":3, "raw":64,
                            "levels":{"1":100,"2":100,"3":64,"4":100}})
        self.assertFalse(self.client.state.pending)
        self.assertEqual(self.client.state.levels, (100, 100, 64, 100))
        self.assertFalse(self.client.set_boost(2, 64))

    def test_full_raw_range_is_preserved_in_queue_and_event_parser(self):
        for raw in range(256):
            client = FanClient(dispatch=lambda fn,*args:fn(*args))
            client.state = FanClientState(running=True,ready=True)
            if raw != 100:
                self.assertTrue(client.set_boost(4,raw))
                self.assertEqual(client.commands.get_nowait()["raw"],raw)
            event = {"protocol":1,"event":"applied","seq":1,"channel":4,"raw":raw,
                     "levels":{"1":100,"2":100,"3":100,"4":raw}}
            self.assertEqual(parse_event(json.dumps(event).encode())["raw"],raw)

    def test_mismatched_ack_stops_instead_of_claiming_success(self):
        self.client.state = FanClientState(running=True, ready=True)
        self.client._event({"event":"applied", "seq":99, "levels":{"1":100,"2":100,"3":100,"4":100}})
        self.assertTrue(self.client.stop_requested.is_set())
        self.assertFalse(self.client.state.ready)

    def test_same_sequence_wrong_channel_raw_or_levels_never_claims_success(self):
        cases = (
            {"channel":2,"raw":64,"levels":{"1":100,"2":64,"3":100,"4":100}},
            {"channel":1,"raw":65,"levels":{"1":65,"2":100,"3":100,"4":100}},
            {"channel":1,"raw":64,"levels":{"1":64,"2":64,"3":100,"4":100}},
        )
        for ack in cases:
            with self.subTest(ack=ack):
                client = FanClient(dispatch=lambda fn, *args: fn(*args))
                client.state = FanClientState(running=True, ready=True)
                self.assertTrue(client.set_boost(1,64))
                client._event({"event":"applied", "seq":1, **ack})
                self.assertTrue(client.stop_requested.is_set())
                self.assertFalse(client.state.ready)
                self.assertNotIn("Boost đã được ghi", client.state.message)

    def test_malformed_ack_is_rejected_at_protocol_boundary(self):
        valid = {"protocol":1,"event":"applied","seq":1,"channel":1,"raw":64,
                 "levels":{"1":64,"2":100,"3":100,"4":100}}
        for change in ({"channel":5}, {"channel":True}, {"raw":256},
                       {"levels":{"1":100,"2":100,"3":100,"4":100}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                parse_event(json.dumps({**valid, **change}).encode())
        with self.assertRaises(ValueError):
            parse_event(b'{"protocol":1,"event":"applied","seq":1,"seq":2,"channel":1,"raw":64,"levels":{"1":64,"2":100,"3":100,"4":100}}')

    def test_client_cooldown_prevents_accidental_fast_second_write(self):
        self.client.state = FanClientState(running=True,ready=True,cooldown_until=102)
        with patch.object(fan_client.time,"monotonic",return_value=101):
            self.assertFalse(self.client.set_boost(1,64))
        self.assertTrue(self.client.commands.empty())
        with patch.object(fan_client.time,"monotonic",return_value=103):
            self.assertTrue(self.client.set_boost(1,64))

    def test_stop_is_not_reported_as_recovered_until_final_ack(self):
        self.client.state = FanClientState(running=True, ready=True)
        self.client.stop()
        self.assertTrue(self.client.state.running)
        self.assertFalse(self.client.state.ready)
        self.client._event({"event":"stopped", "restored":False, "message":"failed"})
        self.assertIn("CHƯA", self.client.state.message)
        self.client._event({"event":"stopped", "restored":True, "message":"done"})
        self.assertIn("Đã xác minh", self.client.state.message)

    def test_event_schema_rejects_invalid_levels_and_unknown_protocol(self):
        for data in ({}, [], {"protocol":2,"event":"ready"},
                     {"protocol":1,"event":"ready","levels":{"1":64,"2":64,"3":100,"4":100}},
                     {"protocol":1,"event":"status","levels":{"1":True,"2":100,"3":100,"4":100}}):
            with self.assertRaises(ValueError):
                parse_event(json.dumps(data).encode())
        with self.assertRaises(ValueError):
            parse_event(b' ' * 8193)

    def test_background_transport_with_real_pipes_but_fake_no_hardware_process(self):
        # This subprocess is only a JSON echo fixture. It imports no app modules,
        # invokes no pkexec, and has no system paths or hardware commands.
        script = '''
import json,sys
def emit(event, **kw):
    print(json.dumps(dict(protocol=1,event=event,**kw)),flush=True)
emit("starting")
levels={str(i):100 for i in range(1,5)}
for line in sys.stdin:
    c=json.loads(line)
    if c["op"]=="start": emit("ready",levels=levels,remaining=55)
    elif c["op"]=="set":
        levels[str(c["channel"])]=c["raw"]
        emit("applied",levels=levels,seq=c["seq"],channel=c["channel"],raw=c["raw"])
        emit("stopped",restored=True,mutated=True,message="fake verified recovery")
        break
    elif c["op"]=="stop":
        emit("stopped",restored=True,mutated=False,message="fake stopped")
        break
'''
        real_popen = subprocess.Popen
        processes = []
        requested = []
        def launch(command, **kwargs):
            requested.append(command)
            process = real_popen([sys.executable, "-I", "-u", "-c", script], **kwargs)
            processes.append(process)
            return process
        with patch.object(fan_client, "fan_deployment_reason", return_value=None), patch.object(fan_client.subprocess, "Popen", side_effect=launch):
            try:
                self.assertTrue(self.client.start())
                deadline = time.monotonic() + 3
                while not self.client.state.ready and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(self.client.state.ready, self.client.state.message)
                self.assertTrue(self.client.set_boost(2, 64))
                while self.client.state.running and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertFalse(self.client.state.running, self.client.state.message)
                self.assertIn("Đã xác minh", self.client.state.message)
                self.assertEqual(requested[0], ["pkexec", str(fan_integrity.FAN_HELPER), "session"])
            finally:
                self.client.stop()
                for process in processes:
                    process.wait(timeout=3)

    def test_timeout_returns_without_waiting_for_stuck_fake_child(self):
        real_popen = subprocess.Popen
        processes = []
        def launch(_command, **kwargs):
            child = real_popen([sys.executable, "-I", "-c", "import time; time.sleep(1.5)"], **kwargs)
            processes.append(child)
            return child
        original_clock = time.monotonic
        calls = 0
        def expired_clock():
            nonlocal calls
            calls += 1
            return 0 if calls == 1 else 181
        with patch.object(fan_client.subprocess, "Popen", side_effect=launch), patch.object(fan_client.time, "monotonic", side_effect=expired_clock):
            started = original_clock()
            self.client._worker()
            elapsed = original_clock() - started
        self.assertLess(elapsed, 1.0)
        self.assertFalse(self.client.state.running)
        self.assertIn("Không tự giả định", self.client.state.message)
        self.assertEqual(len(processes), 1)
        self.assertIsNone(processes[0].poll())
        processes[0].wait(timeout=3)


class FanDeploymentTests(unittest.TestCase):
    def test_installation_alone_never_opens_deployment_gate(self):
        with patch.object(fan_integrity, "fan_candidate_reason", return_value=None), patch.object(fan_integrity, "protected", side_effect=FileNotFoundError):
            self.assertIn("end-to-end", fan_integrity.fan_deployment_reason())

    def test_verified_record_is_bound_to_exact_payload_hardware_and_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory)/"verified.json"
            data = {"protocol":1,"model":fan_integrity.MODEL,"bios":fan_integrity.BIOS,
                    "kernel":fan_integrity.KERNEL,"driver":fan_integrity.DRIVER,
                    "payload_sha256":"test-digest","status":"e2e-verified"}
            with patch.object(fan_integrity,"DEPLOYMENT",record), patch.object(fan_integrity,"fan_candidate_reason",return_value=None), patch.object(fan_integrity,"protected",return_value=True), patch.object(fan_integrity,"payload_digest",return_value="test-digest"):
                record.write_text(json.dumps(data))
                self.assertIsNone(fan_integrity.fan_deployment_reason())
                for key in data:
                    record.write_text(json.dumps({**data,key:"changed"}))
                    self.assertIsNotNone(fan_integrity.fan_deployment_reason(),key)

    def test_writable_record_cannot_enable_ui(self):
        with patch.object(fan_integrity,"fan_candidate_reason",return_value=None), patch.object(fan_integrity,"protected",return_value=False):
            self.assertIn("root",fan_integrity.fan_deployment_reason())

    def test_candidate_rejects_symlinked_or_user_owned_helper(self):
        with patch.object(fan_integrity,"helper_payload_reason",return_value=None), patch.object(fan_integrity,"protected",return_value=False):
            self.assertIn("root",fan_integrity.fan_candidate_reason())

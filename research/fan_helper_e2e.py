#!/usr/bin/python3
"""Explicitly approved installed-helper E2E; no sysfs write in this process.

Normal-user controller/observer; the installed, authenticated helper owns all
mutations and its independent guardian. One channel/run, exclusive transcript,
no retry/sweep, and no production activation in this runner.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time

CONFIRM = "--confirm-installed-fan-helper-e2e"
STAGE_SECONDS = 15


def assess(stages):
    import statistics
    if set(stages) != {"A1", "B", "A2"} or any(len(v) != STAGE_SECONDS for v in stages.values()):
        return {"responsive": False, "reason": "Incomplete 15-sample phases"}
    medians = {key: statistics.median(values[-4:]) for key, values in stages.items()}
    stable = all(max(v[-4:]) - min(v[-4:]) <= max(300, .1 * medians[k]) for k, v in stages.items())
    threshold = max(300, .1 * max(medians["A1"], medians["A2"]))
    up, down = medians["B"] - medians["A1"], medians["B"] - medians["A2"]
    repeated = abs(medians["A1"] - medians["A2"]) <= max(300, .15 * max(medians["A1"], medians["A2"]))
    return {"responsive": stable and repeated and up >= threshold and down >= threshold,
            "median_rpm": medians, "stable_tails": stable, "repeated_low": repeated,
            "increase_rpm": up, "decrease_rpm": down, "minimum_delta_rpm": threshold}


def arguments(argv):
    if not argv or argv[0] != CONFIRM:
        return None
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", type=int, choices=(1, 2, 3, 4), required=True)
    parser.add_argument("--end", choices=("stop", "eof", "heartbeat"), required=True)
    parser.add_argument("--run", type=int, choices=range(1, 10), required=True)
    parser.add_argument("--route", choices=("validation", "production"), default="validation")
    return parser.parse_args(argv[1:])


class Connection:
    def __init__(self, child, event):
        self.child = child
        self.event = event
        self.buffer = b""
        self.messages = []
        self.ready = None
        self.final = None
        self.eof = False
        self.heartbeats = False
        self.next_heartbeat = 0
        self.input_closed = False
        self.audit = None
        self.start_sent = False

    def send(self, value):
        if self.input_closed:
            raise RuntimeError("Input pipe closed")
        self.child.stdin.write((json.dumps(value) + "\n").encode())
        self.child.stdin.flush()
        if value["op"] != "heartbeat":
            self.event("send", command=value)

    def close_input(self):
        self.heartbeats = False
        if not self.input_closed:
            self.child.stdin.close()
            self.input_closed = True
            self.event("stdin-closed")

    def pump(self, timeout=.2):
        from awcc_linux.fan_client import parse_event
        if self.heartbeats and self.final is None and time.monotonic() >= self.next_heartbeat:
            self.send({"op": "heartbeat"})
            self.next_heartbeat = time.monotonic() + 1
        readable, _, _ = select.select([self.child.stdout], [], [], timeout)
        if not readable:
            return
        data = os.read(self.child.stdout.fileno(), 4096)
        if not data:
            self.eof = True
            return
        self.buffer += data
        if len(self.buffer) > 32768:
            raise RuntimeError("Oversize helper response")
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            value = parse_event(line)
            self.messages.append(value)
            self.event("helper-event", payload=value)
            if value["event"] == "starting":
                self.audit = value["audit"]
                self.send({"op": "start"})
                self.start_sent = True
            elif value["event"] == "ready":
                self.ready = value
                self.heartbeats = True
                self.next_heartbeat = 0
            elif value["event"] == "stopped":
                self.final = value
                self.heartbeats = False
            elif value["event"] == "error":
                raise RuntimeError(value.get("message", "Helper rejected request"))

    def wait_for(self, predicate, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return
            if self.final is not None or self.eof:
                raise RuntimeError(f"Helper stopped early: {self.final}")
            self.pump()
        raise TimeoutError("Timed out waiting for helper")

    def request(self, seq, channel, raw):
        self.send({"op": "set", "seq": seq, "channel": channel, "raw": raw})
        self.wait_for(lambda: any(m["event"] == "applied" and m.get("seq") == seq for m in self.messages), 5)
        ack = next(m for m in self.messages if m["event"] == "applied" and m.get("seq") == seq)
        expected = {str(i): raw if i == channel else 100 for i in range(1, 5)}
        if ack["channel"] != channel or ack["raw"] != raw or ack["levels"] != expected:
            raise RuntimeError("Wrong installed-helper ACK")


def record(state):
    return {"profile": state.profile.current, "temperatures": {t.label: t.celsius for t in state.temperatures},
            "fans": [{"channel": f.channel, "rpm": f.rpm, "boost": f.boost} for f in state.awcc_fans],
            "pwm_enable": [f.pwm_enable for f in state.fans]}


def main(argv=None):
    args = arguments(sys.argv[1:] if argv is None else argv)
    if args is None or os.geteuid() == 0:
        return 64
    import awcc_linux
    from awcc_linux.backend import HardwareBackend
    from awcc_linux.fan_integrity import FAN_HELPER, fan_candidate_reason, fan_deployment_reason, payload_digest
    from awcc_linux.fan_policy import DRIVER, check_snapshot
    if "/.local/share/alienware-control-center/venv/" not in str(awcc_linux.__file__):
        raise RuntimeError("Use installed application interpreter, never checkout PYTHONPATH")
    reason = fan_deployment_reason() if args.route == "production" else fan_candidate_reason()
    if reason:
        raise RuntimeError(reason)
    result = Path(__file__).resolve().parent / f"results/hardware-fan-helper-2026-10-15-{args.route}-fan{args.channel}-{args.end}-run{args.run}.jsonl"
    with result.open("x", encoding="utf-8") as transcript:
        def event(kind, **data):
            line = json.dumps({"time": time.time(), "event": kind, **data}, ensure_ascii=False)
            transcript.write(line + "\n")
            transcript.flush()
            print(line, flush=True)

        backend = HardwareBackend()
        def ac():
            return any(p.read_text().strip() == "1" for p in Path("/sys/class/power_supply").glob("AC*/online"))
        def daemon():
            return subprocess.check_output(["/usr/bin/powerprofilesctl", "get"], text=True, timeout=5).strip()
        before = backend.snapshot()
        check_snapshot(before, ac(), starting=True)
        if before.profile.current not in {"balanced", "performance"} or daemon() != before.profile.current:
            raise RuntimeError("Need a matching baseline Balanced/Performance pair")
        if any(f.boost != 0 for f in before.awcc_fans):
            raise RuntimeError("Baseline boosts must all be zero")
        if Path("/sys/module/alienware_wmi/srcversion").read_text().strip() != DRIVER:
            raise RuntimeError("Stock driver changed")
        for unit in ("awccd.service", "i8kmon.service"):
            if subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=5).stdout.strip() != "inactive":
                raise RuntimeError("Competing controller")
        event("preflight", route=args.route, channel=args.channel, end=args.end,
              digest=payload_digest(), module=str(awcc_linux.__file__), snapshot=record(before))
        child = subprocess.Popen(["pkexec", str(FAN_HELPER), "session" if args.route == "production" else "validation-session"],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        connection = Connection(child, event)
        passed = False
        error = None
        after_ok = False
        try:
            connection.wait_for(lambda: connection.ready is not None, 100)
            if connection.ready["remaining"] < (48 if args.end == "stop" else 15):
                raise RuntimeError("Insufficient fixed lease margin; do not extend it")
            stages = {}
            if args.end == "stop":
                for seq, (phase, raw) in enumerate((("A1", 64), ("B", 100), ("A2", 64)), 1):
                    connection.request(seq, args.channel, raw)
                    stages[phase] = []
                    started = time.monotonic()
                    for index in range(1, STAGE_SECONDS + 1):
                        target = started + index
                        while time.monotonic() < target:
                            connection.pump(min(.2, max(0, target - time.monotonic())))
                            if connection.final is not None:
                                raise RuntimeError("Session ended during A/B/A")
                        read_started = time.monotonic()
                        state = backend.snapshot()
                        if time.monotonic() - read_started > 3:
                            raise RuntimeError("Slow independent telemetry")
                        check_snapshot(state, ac(), expected_profile="custom", require_spinning=True,
                                       baseline_hot=max(t.celsius for t in before.temperatures),
                                       levels={i: raw if i == args.channel else 100 for i in range(1, 5)})
                        if daemon() != "power-saver":
                            raise RuntimeError("PPD changed")
                        stages[phase].append(next(f.rpm for f in state.awcc_fans if f.channel == args.channel))
                        event("sample", phase=phase, sample=index, snapshot=record(state))
                evaluation = assess(stages)
                event("evaluation", **evaluation)
                passed = evaluation["responsive"]
                connection.send({"op": "stop"})
                connection.heartbeats = False
            else:
                # Fault paths use only known all-100 initialization, no extra low/raw sweep.
                for _ in range(3):
                    connection.pump(1)
                if args.end == "eof":
                    connection.close_input()
                else:
                    connection.heartbeats = False  # Keep stdin open; test heartbeat, not EOF.
                    event("heartbeat-withheld")
            connection.wait_for(lambda: connection.final is not None, 30)
            if not connection.final.get("restored") or not connection.final.get("mutated"):
                raise RuntimeError("Helper did not confirm a real session and restoration")
            if args.end != "stop":
                if args.end == "heartbeat" and not any(word in connection.final.get("message", "").casefold()
                                                      for word in ("heartbeat", "signal 15", "watchdog")):
                    raise RuntimeError("Session stopped for an unexpected reason, not heartbeat")
                passed = True
        except (Exception, KeyboardInterrupt) as exc:
            error = repr(exc)
            event("test-error", error=error)
        finally:
            if connection.final is None:
                try:
                    connection.close_input()
                    connection.wait_for(lambda: connection.final is not None, 35)
                except Exception as exc:
                    event("final-wait-error", error=repr(exc))
            try:
                exit_code = child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                exit_code = None
                event("helper-still-running", pid=child.pid)  # Never SIGKILL recovery owner.
            if exit_code is None or (args.end != "heartbeat" and exit_code != 0):
                passed = False
            try:
                # Independent observations after process exit, not CLI status alone.
                after_ok = True
                for index in range(4):
                    state = backend.snapshot()
                    good = (state.profile.current == before.profile.current and daemon() == before.profile.current
                            and {f.channel: f.boost for f in state.awcc_fans} == dict.fromkeys(range(1, 5), 0)
                            and len(state.fans) == 4 and all(f.pwm_enable == 2 for f in state.fans))
                    after_ok = after_ok and good
                    event("after-restore", sample=index + 1, ok=good, snapshot=record(state))
                    time.sleep(1)
                after_ok = after_ok and all(f.rpm is not None and f.rpm > 0 for f in state.awcc_fans)
            except Exception as exc:
                after_ok = False
                event("after-restore-error", error=repr(exc))
            event("complete", passed=bool(passed and after_ok and error is None), restored=after_ok,
                  helper_exit=exit_code, final=connection.final, audit=connection.audit, error=error,
                  start_handshake_sent=connection.start_sent,
                  outcome="not-started" if not connection.start_sent else "evaluated" if passed else "aborted",
                  recovery_confirmed=connection.final.get("restored") if connection.final else None)
            for stream in (child.stdin, child.stdout):
                if stream is not None and not stream.closed:
                    stream.close()
        return 0 if passed and after_ok and error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())

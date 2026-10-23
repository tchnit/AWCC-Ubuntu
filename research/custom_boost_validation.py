#!/usr/bin/python3
"""One approved x17 R1 native AWCC experiment, NOT a production actuator.

No PWM, raw SMM, EC access, driver/service mutations, or repeated control tick.
Run through pkexec with isolated Python. An independent root watchdog fences
further test writes and attempts baseline recovery on timeout/parent death.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import signal
import stat
import statistics
import subprocess
import sys
import tempfile
import time

CONFIRM = "--confirm-x17r1-custom-boost-remaining-64-100-64-20s"
APPROVED_CHANNELS = (2, 3, 4)
DRIVER = "28A4134FBF8432C66D7C668"
LEVELS = (("A1", 64), ("B", 100), ("A2", 64))
GLOBAL_SECONDS = 150
CUSTOM_SECONDS = 75
STAGE_SECONDS = 20


def approved_channel(argv):
    if len(argv) != 3 or argv[:2] != [CONFIRM, "--channel"] or argv[2] not in {str(c) for c in APPROVED_CHANNELS}:
        return None
    return int(argv[2])


def stage_boosts(channel, level):
    if channel not in (1, 2, 3, 4) or level not in {64, 100}:
        raise ValueError("Unexpected test channel/level")
    return {i: level if i == channel else 100 for i in range(1, 5)}


def validate(state, ac, ceiling, baseline_hot=None, expected_profile=None,
             expected_boosts=None, require_spinning=False):
    if (state.model, state.bios_version) != ("Alienware x17 R1", "1.27.0"):
        raise RuntimeError("Unexpected model/BIOS")
    if not ac or state.capabilities.external_awccd_controller:
        raise RuntimeError("AC disconnected or controller conflict")
    temps = {t.label: t.celsius for t in state.temperatures}
    cpu = next((t for t in state.temperatures if t.label == "CPU"), None)
    gpu = next((t for t in state.temperatures if t.label == "GPU"), None)
    if not {"CPU", "GPU"} <= temps.keys() or gpu.source != "NVIDIA NVML" or cpu.source != "AWCC WMI":
        raise RuntimeError("CPU/AWCC or GPU/NVIDIA telemetry missing")
    if not all(math.isfinite(t) and 10 <= t < ceiling for t in temps.values()):
        raise RuntimeError(f"Invalid/too-hot telemetry: {temps}")
    if baseline_hot is not None and max(temps.values()) - baseline_hot >= 10:
        raise RuntimeError("Temperature rose by at least 10 C")
    fans = state.awcc_fans
    if sorted(f.channel for f in fans) != [1, 2, 3, 4]:
        raise RuntimeError("AWCC fan topology changed")
    for f in fans:
        if f.boost is None or not 0 <= f.boost <= 255 or f.rpm is None or not 0 <= f.rpm <= 20000:
            raise RuntimeError("Invalid fan telemetry")
        if require_spinning and f.rpm == 0:
            raise RuntimeError(f"Fan {f.channel} stopped after settle")
    if expected_profile is not None and state.profile.current != expected_profile:
        raise RuntimeError(f"Profile changed to {state.profile.current}")
    if expected_boosts is not None and {f.channel:f.boost for f in fans} != expected_boosts:
        raise RuntimeError("Boost read-back changed")


def assess(stages, channel=1):
    if set(stages) != {"A1", "B", "A2"} or any(len(v) < 4 for v in stages.values()):
        return {"responsive": False, "reason": "Insufficient independent stage samples"}
    medians = {name: statistics.median(values[-4:]) for name,values in stages.items()}
    stable = all(max(values[-4:])-min(values[-4:]) <= max(300, .1*medians[name]) for name,values in stages.items())
    threshold = max(300, .1*max(medians["A1"],medians["A2"]))
    up, down = medians["B"]-medians["A1"], medians["B"]-medians["A2"]
    repeated = abs(medians["A1"]-medians["A2"]) <= max(300,.15*max(medians["A1"],medians["A2"]))
    return {"responsive": stable and repeated and up>=threshold and down>=threshold,
            "median_rpm":medians,"increase_rpm":up,"decrease_rpm":down,
            "minimum_delta_rpm":threshold,"stable_tails":stable,"repeated_low":repeated,
            "channel":channel,
            "scope":f"AWCC fan{channel} only; not fixed RPM, four-channel validation or production enablement"}


class Probe:
    def __init__(self, backend, state_dir, channel=1):
        if channel not in (1, 2, 3, 4):
            raise ValueError("Invalid AWCC channel")
        self.channel = channel
        self.backend = backend
        paths = backend._paths()
        if paths.alienware_hwmon is None or paths.platform_profile is None:
            raise RuntimeError("Missing native AWCC provider")
        self.hwmon, self.profile = paths.alienware_hwmon, paths.platform_profile / "profile"
        self.state_dir = state_dir
        self.cancel = state_dir / "verified-restoration"
        self.expired = state_dir / "writes-fenced"
        self.custom_deadline = state_dir / "custom.deadline"
        self.log = os.open(state_dir / "hardware-test.jsonl", os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW, 0o600)
        self.original = None
        self.original_boosts = None

    def event(self, kind, **data):
        line = (json.dumps({"time":time.time(),"event":kind,**data},ensure_ascii=False)+"\n").encode()
        for fd in (self.log, 1):
            try:
                os.write(fd,line)
            except OSError:
                pass  # Broken consumer must never prevent recovery.

    @contextmanager
    def lock(self, name):
        with (self.state_dir/name).open("a") as stream:
            fcntl.flock(stream.fileno(),fcntl.LOCK_EX)
            yield

    def command(self, *args, timeout=5):
        return subprocess.run(args,check=False,capture_output=True,text=True,timeout=timeout)

    def daemon(self):
        result = self.command("/usr/bin/powerprofilesctl","get")
        if result.returncode or result.stdout.strip() not in {"balanced","performance","power-saver"}:
            raise RuntimeError("Cannot read PPD")
        return result.stdout.strip()

    def ac(self):
        sources = list(Path("/sys/class/power_supply").glob("AC*/online"))
        return any(p.read_text().strip()=="1" for p in sources)

    def controllers(self):
        for unit in ("awccd.service","i8kmon.service"):
            if self.command("/usr/bin/systemctl","is-active",unit).stdout.strip() != "inactive":
                raise RuntimeError(f"Competing controller {unit}")

    def fence_check(self):
        if self.expired.exists():
            raise RuntimeError("Further test writes fenced")

    def arm_custom_deadline(self, seconds):
        temporary=self.state_dir/"custom.deadline.next"
        temporary.write_text(str(time.monotonic()+seconds))
        os.replace(temporary,self.custom_deadline)

    def set_ppd(self, mode, recovery=False):
        with self.lock("mutation.lock"):
            if not recovery:
                self.fence_check()
            try:
                result=self.command("/usr/bin/powerprofilesctl","set",mode,timeout=20)
                self.event("ppd-request",mode=mode,returncode=result.returncode,stderr=result.stderr.strip(),recovery=recovery)
            except subprocess.TimeoutExpired:
                self.event("ppd-timeout",mode=mode,recovery=recovery)
        # Actual verification, not CLI status, determines restoration.

    def write(self,path,value,recovery=False):
        with self.lock("mutation.lock"):
            if not recovery:
                self.fence_check()
            start=time.monotonic()
            self.event("native-write-start",node=path.name,value=value,recovery=recovery)
            try:
                path.write_text(str(value)+"\n")
            finally:
                self.event("native-write-finished",node=path.name,value=value,recovery=recovery,
                           elapsed=time.monotonic()-start)

    def sample(self, **validation):
        self.fence_check()
        state = self.backend.snapshot()
        validate(state,self.ac(),**validation)
        if self.daemon() != "power-saver":
            raise RuntimeError("PPD CPU mode changed during test")
        return state

    @staticmethod
    def record(state):
        return {"profile":state.profile.current,"temperatures":{t.label:t.celsius for t in state.temperatures},
                "fans":[{"channel":f.channel,"rpm":f.rpm,"boost":f.boost} for f in state.awcc_fans],
                "pwm_enable":[f.pwm_enable for f in state.fans]}

    def verify_pair(self, mode, profile):
        good=True
        for delay in (0,.4,.6,1):
            time.sleep(delay)
            state=self.backend.snapshot()
            observed=self.daemon()
            self.event("route-verification",daemon=observed,snapshot=self.record(state))
            good=good and state.profile.current==profile and observed==mode
        return good

    def restore(self, actor):
        with self.lock("recovery.lock"):
            if self.cancel.exists():
                return True
            self.expired.touch(mode=0o600)
            self.event("restore-start",actor=actor,original=self.original)
            try:
                # Always bridge: PPD may still have the original coarse mode
                # while the firmware is in Custom. Never direct-write Performance.
                self.set_ppd("balanced",recovery=True)
                if not self.verify_pair("balanced","balanced"):
                    # Balanced sysfs path was independently validated in Phase 5J.
                    self.write(self.profile,"balanced",recovery=True)
                    if not self.verify_pair("balanced","balanced"):
                        raise RuntimeError("Cannot verify Balanced recovery bridge")
                if self.original == "performance":
                    self.set_ppd("performance",recovery=True)
                    if not self.verify_pair("performance","performance"):
                        raise RuntimeError("Cannot verify original Performance")
                # Profile changes can reset boost; restore boosts AFTER profile.
                for channel,value in self.original_boosts.items():
                    self.write(self.hwmon/f"fan{channel}_boost",value,recovery=True)
                restored=True
                for delay in (0,.4,.6,1):
                    time.sleep(delay)
                    state=self.backend.snapshot()
                    observed=self.daemon()
                    boosts={f.channel:f.boost for f in state.awcc_fans}
                    bios_auto=len(state.fans)==4 and all(f.pwm_enable==2 for f in state.fans)
                    restored=restored and state.profile.current==self.original and observed==self.original and boosts==self.original_boosts and bios_auto
                    self.event("restore-sample",actor=actor,daemon=observed,snapshot=self.record(state))
                if not restored:
                    raise RuntimeError("Original profile/boost pair not retained")
                self.cancel.touch(mode=0o600)
                self.event("restore-complete",actor=actor,ok=True)
                return True
            except Exception as exc:
                self.event("restore-complete",actor=actor,ok=False,error=repr(exc))
                # Do not restore zero boosts into an unverified Custom state.
                # Keep the already-approved upper test level while seeking help.
                if self.profile.read_text().strip()=="custom":
                    for channel in range(1,5):
                        try:
                            self.write(self.hwmon/f"fan{channel}_boost",100,recovery=True)
                        except Exception:
                            pass
                return False

    def watchdog(self, parent):
        os.setsid()
        deadline=time.monotonic()+GLOBAL_SECONDS
        while not self.cancel.exists():
            if self.custom_deadline.exists():
                try:
                    deadline=min(deadline,float(self.custom_deadline.read_text()))
                except (OSError,ValueError):
                    deadline=time.monotonic()  # Invalid state triggers recovery, not watchdog death.
            if time.monotonic()>=deadline or os.getppid()!=parent:
                self.expired.touch(mode=0o600)
                self.event("watchdog-fired",parent_alive=os.getppid()==parent)
                try:
                    os.kill(parent,signal.SIGTERM)
                except ProcessLookupError:
                    pass
                self.restore("watchdog")
                os._exit(0)
            time.sleep(.1)
        os._exit(0)

    def run(self):
        state=self.backend.snapshot()
        validate(state,self.ac(),ceiling=61)
        self.controllers()
        if Path("/sys/module/alienware_wmi/srcversion").read_text().strip()!=DRIVER:
            raise RuntimeError("Not validated stock driver")
        if state.kernel!="7.0.0-38-generic" or Path("/sys/class/dmi/id/sys_vendor").read_text().strip()!="Alienware":
            raise RuntimeError("Kernel/vendor mismatch")
        if "custom" not in state.profile.choices:
            raise RuntimeError("Custom not advertised")
        if self.daemon()!=state.profile.current or state.profile.current not in {"balanced","performance"}:
            raise RuntimeError("Original PPD/platform pair not recoverable")
        if len(state.fans)!=4 or any(f.pwm_enable!=2 for f in state.fans):
            raise RuntimeError("Initial BIOS-auto state not intact")
        self.original=state.profile.current
        self.original_boosts={f.channel:f.boost for f in state.awcc_fans}
        self.event("preflight",daemon=self.original,snapshot=self.record(state),state_dir=str(self.state_dir),
                   channel=self.channel,stage_seconds=STAGE_SECONDS,custom_watchdog_seconds=CUSTOM_SECONDS,levels=LEVELS)
        parent=os.getpid()
        watchdog=os.fork()
        if watchdog==0:
            self.watchdog(parent)
        def interrupted(signum,frame):
            raise RuntimeError(f"Interrupted {signum}; restoring original")
        for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):
            signal.signal(sig,interrupted)
        success=restored=False
        custom_requested=False
        evaluation=None
        try:
            self.set_ppd("power-saver")
            if not self.verify_pair("power-saver","low-power"):
                raise RuntimeError("Cannot establish Low Power cooling route")
            end=time.monotonic()+45
            while True:
                state=self.sample(ceiling=70,expected_profile="low-power")
                self.event("cooling",snapshot=self.record(state))
                if max(t.celsius for t in state.temperatures)<=50:
                    break
                if time.monotonic()>=end:
                    raise RuntimeError("Cannot cool to <=50 C within budget")
                time.sleep(2)
            baseline_hot=max(t.celsius for t in state.temperatures)
            self.controllers()
            self.arm_custom_deadline(CUSTOM_SECONDS)
            custom_requested=True
            self.write(self.profile,"custom")
            for channel in range(1,5):
                self.write(self.hwmon/f"fan{channel}_boost",100)
            self.event("custom-initial-boosts",raw=[100]*4)
            time.sleep(2)
            self.sample(ceiling=70,baseline_hot=baseline_hot,expected_profile="custom",expected_boosts={i:100 for i in range(1,5)})
            stages={}
            for name,level in LEVELS:
                self.controllers()
                self.sample(ceiling=70,baseline_hot=baseline_hot,expected_profile="custom")
                self.write(self.hwmon/f"fan{self.channel}_boost",level)
                self.event("stage-request",phase=name,channel=self.channel,raw=level)
                start=time.monotonic()
                stages[name]=[]
                for index in range(1,STAGE_SECONDS+1):
                    time.sleep(max(0,start+index-time.monotonic()))
                    state=self.sample(ceiling=70,baseline_hot=baseline_hot,expected_profile="custom",
                                      expected_boosts=stage_boosts(self.channel,level),require_spinning=index>=4)
                    stages[name].append(next(f.rpm for f in state.awcc_fans if f.channel==self.channel))
                    self.event("stage-sample",phase=name,sample=index,elapsed=time.monotonic()-start,daemon="power-saver",snapshot=self.record(state))
            evaluation=assess(stages,self.channel)
            self.event("evaluation",**evaluation)
            success=evaluation["responsive"]
        except (Exception,KeyboardInterrupt) as exc:
            self.event("test-error",error=repr(exc))
        finally:
            for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):
                signal.signal(sig,signal.SIG_IGN)
            restored=self.restore("parent")
            if not restored:
                self.arm_custom_deadline(0)
            os.waitpid(watchdog,0)
            # The watchdog may have completed a second recovery attempt.
            restored=self.cancel.exists()
            self.event("test-complete",responsive=evaluation["responsive"] if evaluation else None,
                       custom_requested=custom_requested,
                       outcome="not-entered-custom" if not custom_requested else "evaluated" if evaluation else "aborted",
                       restored=restored)
        return 0 if success and restored else 1


def main(argv=None):
    channel=approved_channel(sys.argv[1:] if argv is None else argv)
    if channel is None or os.geteuid()!=0:
        return 64
    os.umask(0o077)
    fd=os.open("/run/awcc-x17r1-native-boost.lock",os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    metadata=os.fstat(fd)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid!=0 or stat.S_IMODE(metadata.st_mode)&0o077:
        raise RuntimeError("Unsafe singleton lock")
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    sys.path.insert(0,"/usr/lib/alienware-control-center")
    from awcc_linux.backend import HardwareBackend
    state_dir=Path(tempfile.mkdtemp(prefix="awcc-native-boost.",dir="/run"))
    probe=Probe(HardwareBackend(),state_dir,channel)
    try:
        return probe.run()
    except Exception as exc:
        probe.event("preflight-error",error=repr(exc))
        return 1
    finally:
        os.close(probe.log)
        os.close(fd)


if __name__=="__main__":
    raise SystemExit(main())

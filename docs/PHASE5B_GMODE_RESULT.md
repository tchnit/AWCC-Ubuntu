# Phase 5B — force_gmode result, 2026-10-09

## Confirmed on this machine

The explicitly approved one-shot test ran at 19:47 local time on Alienware x17 R1,
BIOS 1.27.0, kernel `7.0.0-38-generic`. Baseline: AC online, Balanced,
power-profiles-daemon active, CPU/GPU 41/36 °C, no alienware_wmi module holders.
Original configuration remains `force_platform_profile=1 force_hwmon=1`.

After stopping the daemon, the runner reloaded alienware_wmi with
`force_gmode=1`. Discovery and temperature/RPM reads still worked. The first
Performance write immediately failed with errno 56 (`EBADRQC`, "Invalid request
code"). No Performance sample window was reached; the planned three-second
observation did **not** occur. No SMM, PWM or fan-boost writes were issued.

The normal cleanup's Balanced write while force_gmode was enabled also returned
errno 56. Cleanup nevertheless reloaded the ordinary module with
`force_gmode=0` and restarted the daemon; its conservative success flag remained
false because of the earlier error. The independent watchdog retried at its
deadline and reported restoration success. Test exit status was 1, not success.

Raw evidence: [hardware-test-gmode-2026-10-09.jsonl](../research/results/hardware-test-gmode-2026-10-09.jsonl).

## Verified final state

The watchdog snapshot showed Balanced, daemon active, CPU/GPU 44/36 °C and RPM
6300/6400/6700/5000. Boost read-back briefly showed four zeros in that snapshot.
A subsequent independent read-only check showed boost back at the original
255/250/255/250, RPM 6300/6500/6800/5000, CPU/GPU 44/36 °C, Balanced and daemon
active. Dell SMM `pwm1_enable` through `pwm4_enable` were independently read back
as 2 (BIOS automatic). No runner process remained. No persistent system configuration was
edited and no reboot was performed.

Kernel journal contains unsafe-parameter taint messages, including for explicit
`force_gmode=0` during restoration. That warning alone does not mean G-Mode
remains enabled. Module parameters have sysfs permissions 0, so their current
boolean values cannot be independently read there. The successful reload
command is the evidence for disabling force_gmode. Kernel taint read-back is
12353; no pre-test taint value was collected, so attribution of all bits to this
test would be incorrect. Unloading does not clear kernel taint.

## Interpretation and limits

The hypothesis that merely adding force_gmode makes Performance usable is
rejected for this model/BIOS/kernel. This does not prove that every possible
firmware performance interface is unsupported, nor that a Game Shift toggle
successfully occurred.

Upstream [alienware-wmi-wmax.c](https://github.com/torvalds/linux/blob/master/drivers/platform/x86/dell/alienware-wmi-wmax.c)
maps AWCC failure sentinels to `-EBADRQC`; its G-Mode setter queries Game Shift
status before optional toggling and profile activation. Failure on both
Performance and Balanced is consistent with rejection in that path, but the
sysfs error does not identify the exact failed WMI operation or firmware return
value. This source was inspected as protocol context, not byte-for-byte proof
of Ubuntu's loaded driver implementation.

Follow-up, same date: verified Ubuntu source archive/diff, installed-module
disassembly and offline decoding of the machine's DSDT now locate this failure
at the **Game Shift status query**. The WMAX dispatch lacks method 0x25 and its
default returns 0xFFFFFFFF. No new Game Shift/control call was made; ordinary
read-only sysfs getters were used to verify system state. See
[PHASE5B_AWCC_REJECTION_ANALYSIS.md](PHASE5B_AWCC_REJECTION_ANALYSIS.md); the earlier
uncertainty above is retained as history, not the latest conclusion.

## Project consequence / next investigation

Keep Game Shift/Gaming hardware writes and manual fan curves locked. Do not
repeat the same force_gmode test or permanently enable that module parameter.
This does not cover the separate PPD Performance route verified later in
Phase 5I.
Next useful work is read-only comparison of the exact running Ubuntu
alienware-wmi source and x17 R1 ACPI/WMI methods against the known working
Windows AWCC protocol; only then propose a narrowly instrumented driver test.
Any new module load, firmware call, installation or reboot requires its own
explanation and permission. Phase 5B remains planner/UI-only, not functioning
manual fan control.

Before the hardware test the runner was hardened against concurrent reloads,
post-watchdog writes, reused evidence directories, signal interruption and AC/
telemetry loss. The six additional offline safety tests passed; complete suite:
45 tests passed. There was no second hardware test after code changes.

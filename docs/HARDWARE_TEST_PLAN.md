# Experimental manual-control hardware test plan

Status: design only — not authorized or executed.

## Goal

Determine whether the x17 R1 accepts global BIOS fan-control commands
`0x34a3/0x35a3` through the patched kernel driver, and whether a per-fan state
remains stable after automatic control is disabled.

The test does not attempt a custom curve and does not probe unknown SMM values.

## Required preflight

The read-only checker must pass every gate immediately before the test:

```bash
./research/preflight.py
```

Required state:

- exact DMI match for Alienware x17 R1;
- AC power online;
- CPU/GPU/other sensors at or below 60 °C;
- current profile `balanced`;
- all four channels in BIOS auto (`pwm_enable=2`);
- stock module and four-fan telemetry healthy;
- candidate `vermagic` equal to the running kernel.

Passing preflight is not authorization to run the hardware test.

## Proposed sequence

1. Start an independent telemetry recorder.
2. Stop any app component capable of profile writes.
3. Unload the stock `dell_smm_hwmon` module.
4. Load the experimental module.
5. Confirm the expected interface shape: four `pwmX` nodes and one global,
   write-only `pwm1_enable`. If not exact, abort before any write.
6. Arm a separate 15-second watchdog whose only job is to write BIOS-auto (`2`)
   to global `pwm1_enable`.
7. Set all four fan states to maximum, disable BIOS auto, then set all four to
   maximum again.
8. Confirm RPM telemetry and temperatures remain valid.
9. For only fan1, request middle state for at most 8 seconds while the other
   three remain at maximum. Abort immediately if any sensor rises by 5 °C or
   exceeds 60 °C, telemetry becomes stale, or an SMM call reports failure.
10. Return fan1 to maximum, restore BIOS auto, and cancel the watchdog only
    after the restore write succeeds.
11. Unload the candidate, reload the stock Ubuntu module and confirm all four
    `pwmX_enable` values read `2`.

## Failure handling

Restoration order is always:

```text
all fans maximum → global BIOS auto → unload candidate → load stock module
```

If the global auto write fails, do not continue experimenting. Keep fans at
maximum, attempt module restoration, and prepare for a controlled reboot or
power cycle. Reboot itself requires separate user confirmation unless needed to
prevent an immediate thermal hazard.

## Interpretation

- A single write-only `pwm1_enable` proves only that DMI matching selected the
  global method.
- A successful sysfs write proves only that the SMM call returned success.
- Manual takeover is supported only if the requested middle state remains
  stable for the test window and BIOS auto can subsequently be restored.
- If state is not stable, the `34a3/35a3` hypothesis is rejected; do not try the
  alternative pair in the same session.

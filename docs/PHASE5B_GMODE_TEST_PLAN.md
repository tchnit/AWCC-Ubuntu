# Phase 5B — force_gmode validation plan

## New hypothesis

The upstream `alienware-wmi` driver assigns the `Alienware x17` DMI family to
`generic_quirks`, where `gmode=false`. Consequently, selecting Performance on
the current x17 R1 only activates the ordinary firmware profile and it rolls
back to Balanced after roughly one second.

With `force_gmode=1`, the driver takes a different path: it queries and toggles
AWCC Game Shift through method `0x25`, maps Performance to
`AWCC_PROFILE_SPECIAL_GMODE`, then activates that special profile. This is a
new firmware-handshake hypothesis and is not a repetition of the previous
ordinary profile, custom-profile, boost, or Dell SMM tests.

Primary references:

- Linux Alienware WMI documentation: G-Mode is toggled with Performance on
  supported devices and can be probed with `force_gmode`.
- `alienware-wmi-wmax.c`: x17 uses `generic_quirks`; the G-Mode setter invokes
  `AWCC_OP_GET_GAME_SHIFT_STATUS` / `AWCC_OP_TOGGLE_GAME_SHIFT` before profile
  activation.

## Safety gates

The runner refuses unless:

- DMI is exactly Alienware x17 R1 with BIOS 1.27.0;
- AC is online;
- `power-profiles-daemon` is active and profile is Balanced at baseline;
- AWCC temperature telemetry exists and hottest sensor is below 60 °C;
- `alienware_wmi` has no module holders.

It never reduces fan boost or writes Dell SMM/PWM. Performance/G-Mode is
observed for three seconds with an 85 °C emergency ceiling. A separate process
watchdog restores Balanced, reloads `alienware_wmi` without `force_gmode`, and
starts `power-profiles-daemon`. The normal `finally` path performs the same
restore and verifies the final snapshot.

Runner hardening before execution: a root-owned singleton lock prevents parallel
tests; each run has a fresh private `/run` directory so old evidence is retained.
The parent and watchdog serialize mutations using separately opened flock
descriptors. Expiry prevents any subsequent test write, including after watchdog
restoration. AC loss or missing telemetry aborts the test. SIGTERM/HUP and
KeyboardInterrupt enter normal cleanup. Restoration explicitly sets
`force_gmode=0`; no persistent modprobe configuration is changed. This is a
best-effort userspace watchdog, not protection against a hung kernel/firmware.

## Requires explicit approval

Execution reloads a live kernel driver and toggles a firmware performance
feature. The runner must not be executed without explicit user permission and
interactive PolicyKit authentication.

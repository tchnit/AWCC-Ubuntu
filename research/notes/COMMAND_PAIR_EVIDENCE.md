# Command-pair evidence for Alienware x17 R1

## Result after hardware test

`34a3/35a3` is rejected for the Alienware x17 R1 with BIOS 1.27.0: the patched
kernel driver received `-EINVAL` for both global commands. `30a3/31a3` remains
only an unverified same-generation Dell gaming hypothesis; it is not safe to
use without a separate review and authorized test.

## Evidence for `0x34a3 / 0x35a3`

- A public Arch Linux boot log from an Alienware x17 R1 shows the service
  `dell-bios-fan-control` running together with `i8kmon` and printing
  `BIOS CONTROL DISABLED`.
- The source of that utility defines disable as `0x34a3` and enable as `0x35a3`.
- This is direct evidence that another x17 R1 owner attempted this pair.

Limitation: the utility calls `i8k_smm()` but discards its return value, then
prints success unconditionally. The boot log does not demonstrate that fan
commands remained under manual control. Therefore it is not confirmation.

Hardware result: the exact-model candidate reached the SMM call, but
`dell_smm_call()` returned `-EINVAL`. In this driver that means the firmware
response was unchanged from the requested opcode or its low 16 bits were
`0xffff`. The test stopped before any lower fan-speed request.

## Evidence for `0x30a3 / 0x31a3`

- Dell G15 5511, another 2021 Dell gaming laptop, was added to the upstream
  whitelist with this pair after a user report that BIOS control had to be
  disabled for manual fan control.
- Dell G15 5510 was later added by copying the verified G15 5511 entry.
- XPS 9315 also uses this pair.

Limitation: sharing a generation or AWCC family does not establish identical
SMM semantics. The target's DMI vendor is `Alienware`, not `Dell Inc.`.

## Exact Ubuntu source comparison

The installed module comes from Ubuntu source package `linux-hwe-7.0`
`7.0.0-38.38~24.04.4`. Its official Debian diff contains no patch header for
`drivers/hwmon/dell-smm-hwmon.c`; therefore the relevant file is unchanged from
the package's upstream Linux 7.0 base. Runtime ABI also matches that source.

## Safety decision

- Keep the `34a3/35a3` patch as a rejected research artifact; do not merge or
  expose it through the app.
- Offline preparation of a `30a3/31a3` candidate is acceptable only after the
  evidence is documented. Loading it or writing its global `pwm1_enable`
  requires a new explicit approval and independent recovery plan.
- Raw userspace SMM probing: rejected.

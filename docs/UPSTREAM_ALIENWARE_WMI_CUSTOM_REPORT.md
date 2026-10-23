# Không gửi upstream — evidence `custom` bị nhiễu bởi `awccd`

> Trạng thái: giữ lại như bản nháp lịch sử, **không submit**. Phase 5E đã tìm
> thấy `awccd.service` là một writer root cạnh tranh của profile và fan boost;
> các run bên dưới chưa ghi trạng thái daemon đó. Cần cô lập daemon rồi lặp lại
> một phép thử có attribution trước khi khôi phục bất kỳ kết luận upstream nào.

# Bản nháp lịch sử: `custom` được quảng bá nhưng chưa chứng minh persistent trên x17 R1

## Summary

`alienware-wmi` exposes `custom` in the platform-profile choices on an
Alienware x17 R1, and the historical environment returned to `balanced` with
`power-profiles-daemon` stopped. Phase 5E found an untracked external daemon
that can cause this behavior, so the following hypothesis is not established.

The driver currently adds `PLATFORM_PROFILE_CUSTOM` unconditionally after
probing the firmware resource list. This machine is evidence that the resulting
choice is not usable on every model.

## Environment

```text
Distribution: Ubuntu 24.04.5 LTS
Kernel:       7.0.0-38-generic #38~24.04.4-Ubuntu
Module:       alienware_wmi, srcversion 28A4134FBF8432C66D7C668
Vendor:       Alienware
Product:      Alienware x17 R1
BIOS:         1.27.0
AC power:     online
```

Reported choices:

```text
low-power quiet balanced balanced-performance performance custom
```

## Reproduction and observed behavior

1. Start from `balanced` with `power-profiles-daemon` active.
2. Stop `power-profiles-daemon` and verify that it is inactive.
3. Write `custom` to the active `alienware-wmi` platform-profile node.
4. Poll the profile and AWCC telemetry every 250 ms.

Observed in the isolated test:

- `custom` remained visible for about 1.8 seconds;
- all four `fan*_boost` values read as zero during that interval;
- the profile then returned to `balanced` without userspace intervention.

A second test wrote the safe pre-test boosts `255 / 250 / 255 / 250` immediately
after selecting `custom`. The profile and boosts read back correctly after
14.56885 ms, but the first poll at 255 ms already reported `balanced`. No
lower-speed fan request was made.

Expected behavior: a profile exposed in `choices` should remain selected, or
the unusable profile should not be advertised.

## Source analysis

In current upstream `awcc_platform_profile_probe()`, ordinary profiles are
discovered from firmware resource IDs. The function then unconditionally maps
`AWCC_PROFILE_SPECIAL_CUSTOM` (`0x00`) and sets the custom choice:

```c
/* Every model supports the "custom" profile */
priv->supported_profiles[PLATFORM_PROFILE_CUSTOM] =
        AWCC_PROFILE_SPECIAL_CUSTOM;
__set_bit(PLATFORM_PROFILE_CUSTOM, choices);
```

Source:
<https://github.com/torvalds/linux/blob/master/drivers/platform/x86/dell/alienware-wmi-wmax.c#L1230-L1284>

The x17 R1 result contradicts the assumption in that comment. Possible fixes
for maintainer consideration:

1. expose `custom` only when firmware lists resource ID `0x00`;
2. add a capability/quirk that disables synthetic `custom` on affected models;
3. if activation requires another vendor-specific transaction, perform and
   verify that transaction before reporting the profile as successfully set.

Option 1 appears preferable unless there are known machines that support the
special profile without listing it.

## Safety and recovery

Both tests used an independent 25-second watchdog, temperature ceiling, AC and
DMI gates, exact boost rollback, and service restoration. Final independent
verification reported:

```text
power-profiles-daemon: active
profile:               balanced
fan boosts:            255 / 250 / 255 / 250
CPU/GPU:                42 / 36 °C
```

Logs:

- `research/results/hardware-test-awcc-isolated-boost-2026-10-09.jsonl`
- `research/results/hardware-test-awcc-custom-boost-handshake-2026-10-09.jsonl`
  (`sha256:3a757110d2ab0db0ce4c67a2795e7f3d43d262368949455c91d83861d29073ed`)

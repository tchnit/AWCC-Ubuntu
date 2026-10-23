# Profile-caller attribution candidate — build only

This candidate is generated at build time from the exact Ubuntu HWE 7.0 source
used by the installed kernel. It applies two strict, fuzz-free patches in a
temporary directory:

1. the existing AWCC wrapper logging used in Phase 5C;
2. one rate-limited log at `awcc_platform_profile_set()` with the current PID,
   task command name, requested platform profile and mapped AWCC ID.

It adds no WMI/SMM/PWM/boost call, no profile mapping, no error handling change,
and no fallback. The caller log is placed before the existing setter branch so
a second `Balanced` request can be attributed before WMAX `0x15` begins.

The one approved run showed that the unexpected `Balanced` setter was executed
by `pid=2350, comm=python3`, distinct from the root test runner
(`pid=36666`), after `power-profiles-daemon` had stopped. The process had
already exited when logs could be inspected, so this build does not identify
its executable. See [Phase 5D](../../docs/PHASE5D_PROFILE_CALLER_ATTRIBUTION.md).

Build only:

```bash
bash tools/build-alienware-offline.sh attribution
```

The generated `alienware-wmi.ko` is unsigned and must never be installed or
loaded without separate user approval. The Phase 5C v1 artefact remains in
`../alienware-module-diagnostic/` unchanged.

Current offline artefact: SHA-256
`2dd22cca0e6457ad904d569e580a2a63d01fbd719defd42be35b9e413a3d9482`,
srcversion `4F1D3A34919D6751B4CB2EE`, vermagic
`7.0.0-38-generic SMP preempt mod_unload modversions`.

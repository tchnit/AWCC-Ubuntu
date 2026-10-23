# Profile-caller attribution candidate v3 — build only

This candidate is prepared from the exact Ubuntu HWE 7.0 source used by the
running kernel. It applies strict, fuzz-free patches in a temporary directory:

1. the existing WMAX wrapper logging from Phase 5C;
2. one rate-limited `AWCC_TRACE` record at the start of
   `awcc_platform_profile_set()`.

The v3 record adds numeric thread PID, TGID, parent PID and initial-user-
namespace UID to the v2 `comm`, requested platform profile and AWCC ID. It
does not attempt to read user command lines or cgroup paths: those kernel APIs
are not exported to this external module on the verified Ubuntu header ABI.

It adds no WMI/SMM/PWM/boost call, mapping, retry, fallback or error handling.
The output module is unsigned and must never be installed or loaded without a
new explicit permission for a hardware test.

Build only:

```bash
bash tools/build-alienware-offline.sh attribution-v3
```

Clean local build on 2026-10-10:

```
SHA-256   6682c4411caac9b20eaa678a6ba95375c34d91b0b10efc71cba99c9925cecae7
srcversion 73C7975CFD1F773F9C0C7C0
vermagic  7.0.0-38-generic SMP preempt mod_unload modversions
```

`../attribution_v3_profile_test_runner.py` pins those two identifiers and
requires its own exact confirmation flag before it can invoke the common
watchdog/restoration runner. Building this artefact did not load it.

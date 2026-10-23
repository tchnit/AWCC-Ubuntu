# Logging candidate — loaded once for Phase 5C, then restored

Inputs are the four original driver files extracted from the SHA-256-verified
Ubuntu `linux-hwe-7.0_7.0.0.orig.tar.gz`. The exact package diff
`7.0.0-38.38~24.04.4` has no changes to these files.

Only `awcc_wmi_command()` changes: selective, rate-limited log messages before
and after existing Game Shift and profile activation calls. Logs include method,
operation, argument bytes, transport errno or valid raw reply and mapped errno.
No extra firmware call, fallback, error suppression, resource mapping, DMI quirk,
fan write or automatic-control change is added. All other source is unchanged.

Build only:

```bash
bash tools/build-alienware-offline.sh diagnostic
```

This compiles in a temporary directory without spaces (Kbuild rejects spaces in
external-module paths), then copies the artifact to this directory. There are no
install/load targets. Headers are pinned to `7.0.0-38-generic`.

Artifact at the time of this report:

- name: `alienware_wmi` (same as the stock driver; not side-by-side-loadable);
- vermagic: `7.0.0-38-generic SMP preempt mod_unload modversions`;
- srcversion: `9CD2136C047452D3F372B09`;
- SHA-256: `05f4055f0a9087588e32f8a7b25f30fae228cd81788f042d1a9a8b236e56f878`;
- unsigned; BTF generation skipped because matching `vmlinux` is unavailable.

Hashes may change when rebuilt because of build metadata. Build success is not
hardware validation. Stock driver remains loaded (`28A4134FBF8432C66D7C668`).

Ngày 2026-10-10, artefact đúng hash ở trên đã được nạp đúng một lần trong
phép thử profile Quiet có watchdog. Nó ghi `WMAX 0x15/0x01/0xA3` trả raw `0`,
sau đó thấy một request `0xA0` khác trong lúc PPD inactive. Module Ubuntu gốc,
Balanced và PPD đều đã được khôi phục; log và giới hạn kết luận ở
[Phase 5C](../../docs/PHASE5C_ORDINARY_PROFILE_DIAGNOSTIC.md).

Permission is still required separately before unloading stock driver, loading
this artifact again, changing services/profiles, or rebooting. Do not repeat
the rejected force_gmode test just to obtain redundant logging:
offline AML plus installed-binary analysis already locates its failure at the
Game Shift **query**. This candidate is preparation for an independently scoped
investigation of ordinary-profile acceptance/rollback, which remains unresolved.

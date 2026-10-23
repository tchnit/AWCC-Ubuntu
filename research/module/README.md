# Experimental module build

This directory exists only to prove that the minimal DMI patch compiles against
the running kernel headers. It must not be loaded on hardware without a separate
approved test plan.

The candidate selects `0x34a3/0x35a3` because an x17 R1 boot log shows the
`dell-bios-fan-control` utility, whose source uses that pair. The utility ignores
the SMM return code, so this is not proof of support.

Loading this module would cause a global manual/automatic SMM command to be sent
when `pwm1_enable` is written. No such write is part of the build process.

Because the workspace path contains a space, invoke Kbuild through the wrapper:

```bash
./tools/build-experimental-module.sh
```

The wrapper builds in a temporary path and copies only the `.ko` and
`Module.symvers` results here. It does not call `insmod`, `modprobe`, `rmmod`,
`depmod`, or write sysfs.

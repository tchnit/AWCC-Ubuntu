# Offline comparison only. No install/load targets.
obj-m += alienware-wmi.o
alienware-wmi-y := alienware-wmi-base.o
alienware-wmi-$(CONFIG_ALIENWARE_WMI_LEGACY) += alienware-wmi-legacy.o
alienware-wmi-$(CONFIG_ALIENWARE_WMI_WMAX) += alienware-wmi-wmax.o

KERNEL_BUILD ?= /lib/modules/7.0.0-38-generic/build

.PHONY: all
all:
	$(MAKE) -C "$(KERNEL_BUILD)" M="$(CURDIR)" CC=x86_64-linux-gnu-gcc-13 modules

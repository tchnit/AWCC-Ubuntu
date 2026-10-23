#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="$PROJECT_DIR/research/module"
BUILD_DIR="$(mktemp -d /tmp/awcc-x17r1-build.XXXXXX)"

cleanup() {
  rm -rf -- "$BUILD_DIR"
}
trap cleanup EXIT

cp "$SOURCE_DIR/Makefile" "$SOURCE_DIR/dell-smm-hwmon.c" "$BUILD_DIR/"
make -C "$BUILD_DIR" all
install -m 0644 "$BUILD_DIR/dell-smm-hwmon-x17r1.ko" "$SOURCE_DIR/"
install -m 0644 "$BUILD_DIR/Module.symvers" "$SOURCE_DIR/"

modinfo "$SOURCE_DIR/dell-smm-hwmon-x17r1.ko" | sed -n \
  -e '/^name:/p' -e '/^vermagic:/p' -e '/^signer:/p'
sha256sum "$SOURCE_DIR/dell-smm-hwmon-x17r1.ko"

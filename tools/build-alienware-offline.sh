#!/usr/bin/env bash
# Build only; never load/install the resulting driver.
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VARIANT="${1:-baseline}"
case "$VARIANT" in
  baseline|diagnostic)
    SOURCE_DIR="$PROJECT_DIR/research/alienware-module-$VARIANT"
    OUTPUT_DIR="$SOURCE_DIR"
    PATCHES=()
    ;;
  attribution|attribution-v3)
    SOURCE_DIR="$PROJECT_DIR/research/sources/ubuntu-hwe-7.0/alienware"
    OUTPUT_DIR="$PROJECT_DIR/research/alienware-module-$VARIANT"
    PATCHES=(
      "$OUTPUT_DIR/0001-awcc-wrapper-logging.patch"
      "$OUTPUT_DIR/0002-awcc-profile-caller-attribution.patch"
    )
    ;;
  *) printf 'Use baseline, diagnostic, attribution, or attribution-v3.\n' >&2; exit 64 ;;
esac
BUILD_DIR="$(mktemp -d /tmp/awcc-wmi-build.XXXXXX)"
cleanup() {
  case "$BUILD_DIR" in /tmp/awcc-wmi-build.*) rm -rf -- "$BUILD_DIR" ;; esac
}
trap cleanup EXIT
cp "$OUTPUT_DIR/Makefile" "$SOURCE_DIR/alienware-wmi-base.c" \
  "$SOURCE_DIR/alienware-wmi-legacy.c" "$SOURCE_DIR/alienware-wmi-wmax.c" \
  "$SOURCE_DIR/alienware-wmi.h" "$BUILD_DIR/"
for patch_file in "${PATCHES[@]}"; do
  patch --batch --fuzz=0 -d "$BUILD_DIR" -p1 < "$patch_file"
done
make -C "$BUILD_DIR" all
cp "$BUILD_DIR/alienware-wmi.ko" "$OUTPUT_DIR/alienware-wmi.ko"
cp "$BUILD_DIR/Module.symvers" "$OUTPUT_DIR/Module.symvers"
modinfo "$OUTPUT_DIR/alienware-wmi.ko" | sed -n \
  -e '/^name:/p' -e '/^srcversion:/p' -e '/^vermagic:/p' -e '/^signer:/p'
sha256sum "$OUTPUT_DIR/alienware-wmi.ko"

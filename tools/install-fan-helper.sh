#!/usr/bin/env bash
# Install candidate files ONLY. No fan/profile command, deployment marker or service.
set -euo pipefail
if [[ ${EUID} -ne 0 ]]; then
  echo "Run this installer as root after explicit approval." >&2
  exit 77
fi
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LIB_DIR=/usr/lib/alienware-control-center/awcc_linux
# Refuse a mixed profile/core payload. Update that helper separately if needed.
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -B "$PROJECT_DIR/tools/check-helper.py"
BACKUP_DIR="$(mktemp -d /var/backups/awcc-fan-helper.XXXXXX)"
cp -a -- "$LIB_DIR" "$BACKUP_DIR/library"
if [[ -f /usr/libexec/awcc-fan-helper ]]; then
  cp -a -- /usr/libexec/awcc-fan-helper "$BACKUP_DIR/awcc-fan-helper"
fi
if [[ -f /usr/share/polkit-1/actions/io.github.awcclinux.FanControl.policy ]]; then
  cp -a -- /usr/share/polkit-1/actions/io.github.awcclinux.FanControl.policy "$BACKUP_DIR/policy"
fi
if [[ -f /usr/lib/alienware-control-center/fan-control-verified.json ]]; then
  cp -a -- /usr/lib/alienware-control-center/fan-control-verified.json "$BACKUP_DIR/deployment-record"
fi
echo "Previous files backed up: $BACKUP_DIR"
for module in fan_policy fan_session fan_hardware fan_helper fan_integrity; do
  install -m 0644 "$PROJECT_DIR/src/awcc_linux/$module.py" "$LIB_DIR/$module.py"
done
install -m 0755 "$PROJECT_DIR/data/awcc-fan-helper" /usr/libexec/awcc-fan-helper
install -m 0644 "$PROJECT_DIR/data/io.github.awcclinux.FanControl.policy" \
  /usr/share/polkit-1/actions/io.github.awcclinux.FanControl.policy
echo "Candidate installed; deployment gate remains closed until separate end-to-end validation."

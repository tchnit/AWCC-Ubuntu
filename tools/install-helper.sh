#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this installer as root." >&2
  exit 77
fi

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LIB_DIR=/usr/lib/alienware-control-center

BACKUP_DIR="$(mktemp -d /var/backups/awcc-helper.XXXXXX)"
if [[ -d "$LIB_DIR" ]]; then
  cp -a -- "$LIB_DIR" "$BACKUP_DIR/library"
fi
if [[ -f /usr/libexec/awcc-profile-helper ]]; then
  cp -a -- /usr/libexec/awcc-profile-helper "$BACKUP_DIR/awcc-profile-helper"
fi
if [[ -f /usr/share/polkit-1/actions/io.github.awcclinux.ControlCenter.policy ]]; then
  cp -a -- /usr/share/polkit-1/actions/io.github.awcclinux.ControlCenter.policy "$BACKUP_DIR/policy"
fi
echo "Previous helper backup: $BACKUP_DIR"

# Install a coherent payload while desktop applications are closed. This
# command only installs files; it never invokes the profile setter.
install -d -m 0755 "$LIB_DIR/awcc_linux" /usr/libexec /usr/share/polkit-1/actions
install -m 0644 "$PROJECT_DIR"/src/awcc_linux/*.py "$LIB_DIR/awcc_linux/"
install -m 0755 "$PROJECT_DIR/data/awcc-profile-helper" /usr/libexec/awcc-profile-helper
install -m 0644 \
  "$PROJECT_DIR/data/io.github.awcclinux.ControlCenter.policy" \
  /usr/share/polkit-1/actions/io.github.awcclinux.ControlCenter.policy

PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -B "$PROJECT_DIR/tools/check-helper.py"
echo "Installed the profile helper and PolicyKit action."

#!/usr/bin/env bash
# Install only the unprivileged GTK application for the current desktop user.
# This deliberately does not install/update the privileged profile helper,
# PolicyKit files, kernel modules, drivers, services, or fan configuration.
set -euo pipefail

if [[ ${EUID} -eq 0 ]]; then
  echo "Run this installer as the desktop user, not root." >&2
  exit 77
fi

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
APPLICATIONS_DIR="${DATA_HOME}/applications"
INSTALL_ROOT="${DATA_HOME}/alienware-control-center"
VENV_DIR="${INSTALL_ROOT}/venv"
BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/awcc-wheel.XXXXXX")"
DESKTOP_FILE="${APPLICATIONS_DIR}/io.github.awcclinux.ControlCenter.desktop"
LAUNCHER="${VENV_DIR}/bin/alienware-control-center"

cleanup() {
  rm -rf -- "${BUILD_DIR}"
}
trap cleanup EXIT

"${PYTHON_BIN}" -c '
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
'
# Ubuntu marks its interpreter as externally managed. A dedicated user-data
# venv preserves the distro interpreter and inherits only GTK/libadwaita GI
# bindings from the system packages. The wheel is built and installed locally;
# --no-index guarantees the operation does not access package indexes.
"${PYTHON_BIN}" -m pip wheel \
  --no-deps --no-build-isolation --wheel-dir "${BUILD_DIR}" "${PROJECT_DIR}"
"${PYTHON_BIN}" -m venv --system-site-packages "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install \
  --no-index --no-deps --force-reinstall "${BUILD_DIR}"/*.whl

install -d -m 0755 "${APPLICATIONS_DIR}" "${INSTALL_ROOT}"
while IFS= read -r line; do
  if [[ "${line}" == Exec=* ]]; then
    printf 'Exec="%s"\n' "${LAUNCHER}"
  else
    printf '%s\n' "${line}"
  fi
done < "${PROJECT_DIR}/data/io.github.awcclinux.ControlCenter.desktop" > "${DESKTOP_FILE}"
chmod 0644 "${DESKTOP_FILE}"

echo "Installed Alienware Control Center for ${USER}."
echo "Desktop entry: ${DESKTOP_FILE}"
echo "Launcher: ${LAUNCHER}"
echo "The privileged helper is intentionally unchanged."

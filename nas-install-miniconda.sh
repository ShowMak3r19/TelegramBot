#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

INSTALL_DIR="${TGBOT_MINICONDA_DIR:-$PWD/.miniconda}"
ARCH="$(uname -m)"

case "$ARCH" in
  x86_64|amd64)
    INSTALLER_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh"
    ;;
  aarch64|arm64)
    INSTALLER_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh"
    ;;
  *)
    echo "Unsupported architecture: $ARCH"
    exit 1
    ;;
esac

if [ -x "$INSTALL_DIR/bin/conda" ]; then
  echo "Miniconda already exists: $INSTALL_DIR"
  "$INSTALL_DIR/bin/conda" --version
  exit 0
fi

TMP_INSTALLER="$(mktemp -t miniconda.XXXXXX.sh)"
cleanup() {
  rm -f "$TMP_INSTALLER"
}
trap cleanup EXIT

echo "Downloading Miniconda for $ARCH..."
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$INSTALLER_URL" -o "$TMP_INSTALLER"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$TMP_INSTALLER" "$INSTALLER_URL"
else
  echo "Neither curl nor wget is available. Install curl or wget first."
  exit 1
fi

echo "Installing Miniconda into: $INSTALL_DIR"
if [ -d "$INSTALL_DIR" ]; then
  bash "$TMP_INSTALLER" -b -u -p "$INSTALL_DIR"
else
  bash "$TMP_INSTALLER" -b -p "$INSTALL_DIR"
fi

"$INSTALL_DIR/bin/conda" config --set auto_activate_base false
"$INSTALL_DIR/bin/conda" --version

echo "Done. Next run: ./nas-conda-setup.sh"

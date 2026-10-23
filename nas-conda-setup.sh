#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

ENV_NAME="${TGBOT_CONDA_ENV:-telegrambot}"

find_conda() {
  if command -v conda >/dev/null 2>&1; then
    command -v conda
    return 0
  fi
  for candidate in \
    "$PWD/.miniconda/bin/conda" \
    "$HOME/miniconda3/bin/conda" \
    "$HOME/anaconda3/bin/conda" \
    "/opt/conda/bin/conda" \
    "/usr/local/miniconda3/bin/conda"; do
    if [ -x "$candidate" ]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

CONDA_BIN="$(find_conda || true)"
if [ -z "$CONDA_BIN" ]; then
  echo "conda not found. Install Miniconda on the NAS first."
  exit 1
fi

mkdir -p runtime/data runtime/logs runtime/tmp sessions

if [ ! -f config.json ]; then
  cp config.example.json config.json
  echo "Created config.json from config.example.json"
fi

"$CONDA_BIN" info >/dev/null

if "$CONDA_BIN" env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  echo "Updating conda env: $ENV_NAME"
  "$CONDA_BIN" env update -n "$ENV_NAME" -f environment.yml --prune
else
  echo "Creating conda env: $ENV_NAME"
  "$CONDA_BIN" env create -n "$ENV_NAME" -f environment.yml
fi

echo "Done. Start with: ./nas-conda-run.sh"

#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

ENV_NAME="${TGBOT_CONDA_ENV:-telegrambot}"
CONFIG_PATH="${TGBOT_CONFIG:-config.json}"

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
  echo "conda not found. Run ./nas-conda-setup.sh first."
  exit 1
fi

mkdir -p runtime/data runtime/logs runtime/tmp sessions

if [ ! -f "$CONFIG_PATH" ]; then
  cp config.example.json "$CONFIG_PATH"
  echo "Created $CONFIG_PATH from config.example.json"
fi

eval "$("$CONDA_BIN" shell.bash hook)"
conda activate "$ENV_NAME"

exec python -m telegram_bot --config "$CONFIG_PATH"

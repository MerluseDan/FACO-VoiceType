#!/usr/bin/env bash
set -Eeuo pipefail
SOURCE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Python 3.9+ is required. Install python3 from your Linux package manager.' >&2
  exit 1
fi
python3 "$SOURCE/scripts/install.py"
if [[ -t 0 && -z "${FACO_INSTALL_NONINTERACTIVE:-}" ]]; then
  printf '\nPress Enter to open FACO Resource Watch... '
  read -r _ || true
  "$HOME/.local/bin/faco-resource-watch" open || true
  printf '\nPress Enter to close this installer terminal... '
  read -r _ || true
fi

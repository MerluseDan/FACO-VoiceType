#!/usr/bin/env bash
set -u
SOURCE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LAUNCH="$HOME/.local/bin/faco-resource-watch"
printf 'FACO Resource Watch | Launcher\n'
if [[ -x "$LAUNCH" ]]; then
  "$LAUNCH" open
else
  echo 'FACO Resource Watch not installed. Starting installer.'
  "$SOURCE/install.sh"
fi
if [[ -t 0 ]]; then
  printf '\nPress Enter to close this terminal... '
  read -r _ || true
fi

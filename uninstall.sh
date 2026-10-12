#!/usr/bin/env bash
set -Eeuo pipefail
SOURCE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SOURCE/scripts/uninstall.py" "$@"

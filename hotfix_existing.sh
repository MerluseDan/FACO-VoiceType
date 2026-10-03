#!/usr/bin/env bash
set -Eeuo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || printf '%s/Desktop' "$HOME")"
LOG_DIR="$DESKTOP_DIR/Logs/FACO VoiceType"
mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/hotfix.log") 2>&1

printf '\n=== FACO VoiceType v1.2.1 canonical migration/update ===\n'
printf 'This updater uses the full installer migration engine so the working runtime/settings are reused rather than redownloaded.\n'
printf 'No dependency download should occur unless the existing installation is actually missing a required component.\n\n'
exec "$HERE/install.sh"

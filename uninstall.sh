#!/usr/bin/env bash
set -Eeuo pipefail
FACO_ROOT="${FACO_RESOURCE_ROOT:-/media/owner/Faco Resources1}"
APP_ROOT="$FACO_ROOT/FACO/apps/voicetype"
STATE_ROOT="$FACO_ROOT/_state/apps/voicetype"
DATA_ROOT="$FACO_ROOT/_data/apps/voicetype"
SHARED_ROOT="$FACO_ROOT/_shared"
ENV_ROOT="$SHARED_ROOT/environments/faco-voicetype"

if [[ -f "$HOME/.config/systemd/user/ydotoold.service" ]] && grep -q "FACO VoiceType managed service" "$HOME/.config/systemd/user/ydotoold.service"; then
  systemctl --user disable --now ydotoold.service 2>/dev/null || true
  rm -f "$HOME/.config/systemd/user/ydotoold.service"
fi
rm -f "$HOME/.config/autostart/faco-voicetype.desktop" \
      "$HOME/.local/share/applications/faco-voicetype.desktop"
if [[ -L "$HOME/.config/faco-voicetype" ]]; then
  rm -f "$HOME/.config/faco-voicetype"
fi
rm -f "$SHARED_ROOT/registry/apps/voicetype.json" "$SHARED_ROOT/registry/capabilities/voicetype.json"
systemctl --user daemon-reload 2>/dev/null || true
sudo rm -f /etc/udev/rules.d/70-faco-voicetype.rules /etc/modules-load.d/faco-voicetype.conf
sudo udevadm control --reload-rules || true
sudo udevadm trigger --subsystem-match=input || true
sudo udevadm trigger --name-match=uinput || true
cat <<EOF
FACO VoiceType desktop/system integration removed.
Preserved intentionally:
  App source : $APP_ROOT
  State      : $STATE_ROOT
  Data       : $DATA_ROOT
  Runtime    : $ENV_ROOT
Nothing was moved to Trash or silently deleted.
EOF

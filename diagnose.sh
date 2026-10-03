#!/usr/bin/env bash
set -u
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
FACO_ROOT="${FACO_RESOURCE_ROOT:-/media/owner/Faco Resources1}"
APP_ROOT="${FACO_VOICETYPE_APP_ROOT:-$FACO_ROOT/FACO/apps/voicetype}"
STATE_ROOT="${FACO_VOICETYPE_STATE_ROOT:-$FACO_ROOT/_state/apps/voicetype}"
DATA_ROOT="${FACO_VOICETYPE_DATA_ROOT:-$FACO_ROOT/_data/apps/voicetype}"
SHARED_ROOT="${FACO_SHARED_ROOT:-$FACO_ROOT/_shared}"
ENV_ROOT="${FACO_VOICETYPE_ENV_ROOT:-$SHARED_ROOT/environments/faco-voicetype}"
pass(){ printf '[PASS] %s\n' "$*"; }
warn(){ printf '[WARN] %s\n' "$*"; }
fail(){ printf '[FAIL] %s\n' "$*"; }

echo "FACO VoiceType v1.2.1 diagnostics"
echo "Session: ${XDG_SESSION_TYPE:-unknown}  Wayland: ${WAYLAND_DISPLAY:-none}  X11: ${DISPLAY:-none}"
echo "FACO root : $FACO_ROOT"
echo "App root  : $APP_ROOT"
echo "State root: $STATE_ROOT"
echo "Data root : $DATA_ROOT"
echo "Runtime   : $ENV_ROOT"

[[ -d "$FACO_ROOT" ]] && pass "canonical FACO root mounted" || fail "canonical FACO root missing"
[[ -d "$APP_ROOT/src/faco_voicetype" ]] && pass "canonical app source present" || fail "canonical app source missing"
[[ -d "$STATE_ROOT" ]] && pass "canonical state directory present" || fail "canonical state directory missing"
[[ -d "$DATA_ROOT" ]] && pass "canonical data directory present" || fail "canonical data directory missing"
[[ -x "$ENV_ROOT/bin/python" ]] && pass "shared canonical Python environment present" || fail "canonical runtime missing"

for cmd in ydotool ydotoold wl-copy xdotool xclip pactl; do
  command -v "$cmd" >/dev/null 2>&1 && pass "$cmd -> $(command -v "$cmd")" || warn "$cmd missing"
done

if systemctl --user is-active --quiet ydotoold.service 2>/dev/null; then
  pass "ydotoold user service active"
elif systemctl is-active --quiet ydotoold.service 2>/dev/null; then
  pass "ydotoold system service active"
else
  warn "ydotoold service not active"
fi
for sock in "/run/user/$(id -u)/.ydotool_socket" /tmp/.ydotool_socket; do
  [[ -S "$sock" ]] && pass "ydotool socket: $sock"
done

[[ -e /dev/uinput && -w /dev/uinput ]] && pass "/dev/uinput writable" || warn "/dev/uinput is not writable by this user"
readable=0
for ev in /dev/input/event*; do
  [[ -e "$ev" ]] || continue
  props="$(udevadm info -q property -n "$ev" 2>/dev/null || true)"
  if grep -qE '^ID_INPUT_(MOUSE|POINTINGSTICK)=1$' <<<"$props"; then
    if [[ -r "$ev" ]]; then pass "mouse event readable: $ev"; readable=$((readable+1)); else warn "mouse event not readable: $ev"; fi
  fi
done
[[ $readable -gt 0 ]] || warn "No readable mouse event device found"

if command -v nvidia-smi >/dev/null 2>&1; then
  pass "NVIDIA driver available: $(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null | head -1)"
else
  warn "nvidia-smi unavailable; CPU transcription will still work"
fi

if [[ -L "$HOME/.config/faco-voicetype" ]]; then
  link="$(readlink -f "$HOME/.config/faco-voicetype" 2>/dev/null || true)"
  [[ "$link" == "$(readlink -f "$STATE_ROOT" 2>/dev/null || true)" ]] && pass "legacy config path bridges to canonical state" || warn "legacy config symlink points elsewhere: $link"
else
  warn "legacy config compatibility symlink missing"
fi

if [[ -x "$ENV_ROOT/bin/python" ]]; then
  echo
  export FACO_RESOURCE_ROOT="$FACO_ROOT" FACO_VOICETYPE_APP_ROOT="$APP_ROOT" \
         FACO_VOICETYPE_STATE_ROOT="$STATE_ROOT" FACO_VOICETYPE_DATA_ROOT="$DATA_ROOT" \
         FACO_VOICETYPE_ENV_ROOT="$ENV_ROOT"
  PYTHONPATH="$APP_ROOT/src" "$ENV_ROOT/bin/python" "$APP_ROOT/selftest.py" || true
fi

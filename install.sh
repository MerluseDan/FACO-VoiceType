#!/usr/bin/env bash
set -Eeuo pipefail

PAYLOAD_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
USER_GROUP="$(id -gn "$USER_NAME")"
USER_UID="$(id -u "$USER_NAME")"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || printf '%s/Desktop' "$USER_HOME")"
LOG_DIR="$DESKTOP_DIR/Logs/FACO VoiceType"
FACO_ROOT="${FACO_RESOURCE_ROOT:-/media/owner/Faco Resources1}"
APP_ROOT="$FACO_ROOT/FACO/apps/voicetype"
STATE_ROOT="$FACO_ROOT/_state/apps/voicetype"
DATA_ROOT="$FACO_ROOT/_data/apps/voicetype"
SHARED_ROOT="$FACO_ROOT/_shared"
ENV_ROOT="$SHARED_ROOT/environments/faco-voicetype"
REGISTRY_ROOT="$SHARED_ROOT/registry"
AUTOSTART="$USER_HOME/.config/autostart/faco-voicetype.desktop"
DESKTOP_APP="$USER_HOME/.local/share/applications/faco-voicetype.desktop"
LEGACY_CONFIG="$USER_HOME/.config/faco-voicetype"
CUDA_PATH_FILE="$STATE_ROOT/cuda_lib_paths"
TOTAL_STEPS=11
CURRENT_STEP=0
START_TS=$(date +%s)
OLD_TARGET=""
OLD_VENV=""
COPIED_OLD_VENV=0

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_DIR/install.log") 2>&1

progress() {
  local label="$1"
  local estimate="${2:-varies by machine}"
  local pct width filled empty elapsed avg remain eta bar_fill bar_empty
  width=32
  CURRENT_STEP=$((CURRENT_STEP + 1))
  pct=$(( CURRENT_STEP * 100 / TOTAL_STEPS ))
  filled=$(( pct * width / 100 ))
  empty=$(( width - filled ))
  elapsed=$(( $(date +%s) - START_TS ))
  eta="measuring"
  if (( CURRENT_STEP > 1 && elapsed > 0 )); then
    avg=$(( elapsed / (CURRENT_STEP - 1) ))
    remain=$(( TOTAL_STEPS - CURRENT_STEP + 1 ))
    eta="~$(( avg * remain ))s overall"
  fi
  printf -v bar_fill '%*s' "$filled" ''; bar_fill=${bar_fill// /#}
  printf -v bar_empty '%*s' "$empty" ''; bar_empty=${bar_empty// /-}
  printf '\n[%s%s] %3d%%  Step %d/%d\n' "$bar_fill" "$bar_empty" "$pct" "$CURRENT_STEP" "$TOTAL_STEPS"
  printf '  %s\n  Expected: %s | ETA: %s\n' "$label" "$estimate" "$eta"
}

pause_on_failure() {
  local rc=$?
  trap - ERR
  printf '\nINSTALLATION FAILED (exit %d).\n' "$rc"
  printf 'Log: %s/install.log\n' "$LOG_DIR"
  printf 'The terminal is intentionally staying open so the useful error does not vanish into the void.\n'
  read -r -p 'Press Enter when you are finished reviewing the error...' _ || true
  exit "$rc"
}
trap pause_on_failure ERR

printf '\n=== FACO VoiceType v1.2.1 canonical installer ===\n'
printf 'Payload : %s\n' "$PAYLOAD_ROOT"
printf 'FACO    : %s\n' "$FACO_ROOT"
printf 'App     : %s\n' "$APP_ROOT"
printf 'State   : %s\n' "$STATE_ROOT"
printf 'Data    : %s\n' "$DATA_ROOT"
printf 'Runtime : %s\n' "$ENV_ROOT"
printf 'Logs    : %s\n\n' "$LOG_DIR"

if [[ $EUID -eq 0 ]]; then
  echo "Run install.sh as the normal desktop user, not with sudo. The installer requests sudo only for system integration."
  read -r -p 'Press Enter to close this installer session...' _ || true
  exit 2
fi

progress "Verify the canonical FACO storage root and create the application layout" "a few seconds"
if [[ ! -d "$FACO_ROOT" ]]; then
  echo "Canonical FACO root is not mounted: $FACO_ROOT"
  echo "VoiceType will not silently dump itself onto the system drive. Mount FACO Resources1 and rerun the installer."
  false
fi
if [[ ! -w "$FACO_ROOT" ]]; then
  echo "Canonical FACO root is not writable by $USER_NAME: $FACO_ROOT"
  false
fi
mkdir -p "$FACO_ROOT/FACO/apps" "$STATE_ROOT" "$DATA_ROOT" "$SHARED_ROOT/environments" \
         "$REGISTRY_ROOT/apps" "$REGISTRY_ROOT/capabilities"

progress "Discover the previous VoiceType install so settings and runtime can be migrated instead of duplicated" "under 5 seconds"
if [[ -f "$AUTOSTART" ]]; then
  EXEC_LINE="$(awk -F= '/^Exec=/{sub(/^Exec=/,""); print; exit}' "$AUTOSTART" || true)"
  if [[ "$EXEC_LINE" == \"*\" && "$EXEC_LINE" == *\" ]]; then
    EXEC_LINE="${EXEC_LINE:1:${#EXEC_LINE}-2}"
  fi
  if [[ -n "$EXEC_LINE" ]]; then
    OLD_TARGET="$(dirname "$EXEC_LINE")"
    [[ -d "$OLD_TARGET/.venv" ]] && OLD_VENV="$OLD_TARGET/.venv"
  fi
fi
if [[ -n "$OLD_TARGET" ]]; then
  printf 'Previous install: %s\n' "$OLD_TARGET"
  [[ -n "$OLD_VENV" ]] && printf 'Previous runtime: %s\n' "$OLD_VENV"
else
  echo "No previous autostart-managed VoiceType installation was found."
fi

# Stop an old running instance before touching its files.
if [[ -n "$OLD_TARGET" ]]; then
  PIDS="$(pgrep -f "${OLD_TARGET// /.*}/.venv/bin/python.*-m faco_voicetype" || true)"
  if [[ -n "$PIDS" ]]; then
    kill -TERM $PIDS 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      sleep 0.15
      pgrep -f "${OLD_TARGET// /.*}/.venv/bin/python.*-m faco_voicetype" >/dev/null || break
    done
  fi
fi

progress "Check/install Linux integration packages needed for microphone, tray, mouse capture and text injection" "seconds when already installed; apt runs only for genuinely missing packages"
REQUIRED_PACKAGES=(
  python3-venv python3-pip python3-dev build-essential libportaudio2
  ydotool wl-clipboard xdotool xclip pulseaudio-utils
  libxcb-cursor0 libegl1 libgl1 libxkbcommon-x11-0 rsync
)
MISSING_PACKAGES=()
for pkg in "${REQUIRED_PACKAGES[@]}"; do
  if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q 'ok installed'; then
    MISSING_PACKAGES+=("$pkg")
  fi
done
if (( ${#MISSING_PACKAGES[@]} )); then
  echo "Missing system packages: ${MISSING_PACKAGES[*]}"
  echo "Only the missing packages will be installed."
  sudo apt-get update
  sudo apt-get install -y "${MISSING_PACKAGES[@]}"
else
  echo "All required system packages are already installed; skipping apt download/update."
fi

progress "Deploy the immutable VoiceType source into FACO/apps/voicetype" "usually under 5 seconds"
mkdir -p "$APP_ROOT"
if [[ "$(readlink -f "$PAYLOAD_ROOT")" != "$(readlink -f "$APP_ROOT" 2>/dev/null || printf '%s' "$APP_ROOT")" ]]; then
  rsync -a --delete \
    --exclude '.venv/' --exclude '__pycache__/' --exclude '.pytest_cache/' --exclude '.git/' \
    "$PAYLOAD_ROOT/" "$APP_ROOT/"
fi
chmod +x "$APP_ROOT/install.sh" "$APP_ROOT/run.sh" "$APP_ROOT/diagnose.sh" "$APP_ROOT/hotfix_existing.sh" "$APP_ROOT/uninstall.sh"

progress "Move persistent configuration into _state and create the legacy compatibility bridge" "under 5 seconds"
if [[ -L "$LEGACY_CONFIG" ]]; then
  CURRENT_LINK="$(readlink -f "$LEGACY_CONFIG" 2>/dev/null || true)"
  if [[ "$CURRENT_LINK" != "$(readlink -f "$STATE_ROOT")" ]]; then
    rm -f "$LEGACY_CONFIG"
  fi
fi
if [[ -d "$LEGACY_CONFIG" && ! -L "$LEGACY_CONFIG" ]]; then
  rsync -a "$LEGACY_CONFIG/" "$STATE_ROOT/"
  rm -rf "$LEGACY_CONFIG"
fi
mkdir -p "$(dirname "$LEGACY_CONFIG")"
[[ -e "$LEGACY_CONFIG" || -L "$LEGACY_CONFIG" ]] || ln -s "$STATE_ROOT" "$LEGACY_CONFIG"

progress "Reuse/migrate the existing Python runtime into _shared/environments before installing anything new" "seconds if already canonical; migration time depends on old environment size"
if [[ ! -x "$ENV_ROOT/bin/python" && -n "$OLD_VENV" && -x "$OLD_VENV/bin/python" ]]; then
  echo "Migrating the already-working runtime instead of downloading dependencies again."
  mkdir -p "$ENV_ROOT"
  rsync -a --info=progress2 "$OLD_VENV/" "$ENV_ROOT/"
  COPIED_OLD_VENV=1
  # Refresh venv metadata/scripts at the new canonical location while retaining site-packages.
  python3 -m venv --upgrade "$ENV_ROOT"
fi
if [[ ! -x "$ENV_ROOT/bin/python" ]]; then
  python3 -m venv "$ENV_ROOT"
fi
"$ENV_ROOT/bin/python" -m pip --version
PIP_LOCAL_ARGS=()
for wheel_dir in "$SHARED_ROOT/wheelhouse" "$SHARED_ROOT/python_wheels" "$SHARED_ROOT/wheels" "$SHARED_ROOT/downloads"; do
  [[ -d "$wheel_dir" ]] && PIP_LOCAL_ARGS+=(--find-links "$wheel_dir")
done
echo "Checking the existing runtime/local FACO caches with networking disabled first..."
if "$ENV_ROOT/bin/python" -m pip install --no-index "${PIP_LOCAL_ARGS[@]}" -r "$APP_ROOT/requirements.txt"; then
  echo "Python dependencies satisfied entirely from the existing runtime/FACO caches; no network download used."
else
  echo "A required Python package is not available in the existing runtime/local FACO caches."
  echo "Falling back to the package index only for unresolved requirements."
  "$ENV_ROOT/bin/python" -m pip install --prefer-binary "${PIP_LOCAL_ARGS[@]}" -r "$APP_ROOT/requirements.txt"
fi

progress "Resolve CUDA from system/shared FACO resources; network is the absolute last resort" "under 15 seconds when reusable; longer only if a genuinely missing GPU runtime must download"
rm -f "$CUDA_PATH_FILE"
SYSTEM_CUDNN=""; SYSTEM_CUBLAS=""
LDCONFIG_BIN="$(command -v ldconfig 2>/dev/null || true)"
if [[ -z "$LDCONFIG_BIN" ]]; then
  for candidate in /usr/sbin/ldconfig /sbin/ldconfig; do
    [[ -x "$candidate" ]] && { LDCONFIG_BIN="$candidate"; break; }
  done
fi
if [[ -n "$LDCONFIG_BIN" ]]; then
  SYSTEM_CUDNN="$("$LDCONFIG_BIN" -p 2>/dev/null | awk '/libcudnn\.so\.9/{print $NF; exit}' || true)"
  SYSTEM_CUBLAS="$("$LDCONFIG_BIN" -p 2>/dev/null | awk '/libcublas\.so\.12/{print $NF; exit}' || true)"
fi
if command -v nvidia-smi >/dev/null 2>&1; then
  if [[ -n "$SYSTEM_CUDNN" && -n "$SYSTEM_CUBLAS" ]]; then
    echo "Reusing system CUDA runtime."
  else
    SHARED_CUDNN="$(find -L "$SHARED_ROOT" -type f -name 'libcudnn.so.9*' -not -path "$ENV_ROOT/*" -print -quit 2>/dev/null || true)"
    SHARED_CUBLAS="$(find -L "$SHARED_ROOT" -type f -name 'libcublas.so.12*' -not -path "$ENV_ROOT/*" -print -quit 2>/dev/null || true)"
    if [[ -n "$SHARED_CUDNN" && -n "$SHARED_CUBLAS" ]]; then
      CUDA_DIRS="$(printf '%s\n%s\n' "$(dirname "$SHARED_CUDNN")" "$(dirname "$SHARED_CUBLAS")" | awk '!seen[$0]++' | paste -sd: -)"
      printf '%s\n' "$CUDA_DIRS" > "$CUDA_PATH_FILE"
      echo "Reusing FACO shared CUDA libraries:"
      echo "  cuDNN : $SHARED_CUDNN"
      echo "  cuBLAS: $SHARED_CUBLAS"
    else
      CUDNN_WHEEL="$(find "$SHARED_ROOT" -type f -iname 'nvidia_cudnn_cu12-*.whl' -print -quit 2>/dev/null || true)"
      CUBLAS_WHEEL="$(find "$SHARED_ROOT" -type f -iname 'nvidia_cublas_cu12-*.whl' -print -quit 2>/dev/null || true)"
      if [[ -n "$CUDNN_WHEEL" && -n "$CUBLAS_WHEEL" ]]; then
        echo "Using cached NVIDIA wheels with zero network download."
        "$ENV_ROOT/bin/python" -m pip install "$CUBLAS_WHEEL" "$CUDNN_WHEEL"
      else
        # The migrated environment may already contain the packages, even if ldconfig/shared scans do not.
        if "$ENV_ROOT/bin/python" - <<'PY' >/dev/null 2>&1
import importlib.util
raise SystemExit(0 if importlib.util.find_spec('nvidia.cudnn.lib') and importlib.util.find_spec('nvidia.cublas.lib') else 1)
PY
        then
          echo "Reusing NVIDIA CUDA wheels already present inside the canonical VoiceType runtime."
        else
          echo "No compatible reusable CUDA runtime or cached wheels were found."
          echo "UNAVOIDABLE DOWNLOAD: nvidia-cublas-cu12 + nvidia-cudnn-cu12; this can exceed 1 GB."
          echo "Reason: CTranslate2 CUDA requires these libraries and no compatible local copy was found."
          echo "Target: $ENV_ROOT"
          "$ENV_ROOT/bin/python" -m pip install 'nvidia-cublas-cu12' 'nvidia-cudnn-cu12==9.*'
        fi
      fi
    fi
  fi
else
  echo "No NVIDIA driver detected; CPU transcription remains available."
fi

progress "Install mouse/uinput permissions, autostart, ydotool service and FACO capability registry" "about 5-15 seconds"
sudo tee /etc/udev/rules.d/70-faco-voicetype.rules >/dev/null <<RULES
SUBSYSTEM=="input", KERNEL=="event*", ENV{ID_INPUT_MOUSE}=="1", OWNER="$USER_NAME", MODE="0600", TAG+="uaccess"
SUBSYSTEM=="input", KERNEL=="event*", ENV{ID_INPUT_POINTINGSTICK}=="1", OWNER="$USER_NAME", MODE="0600", TAG+="uaccess"
KERNEL=="uinput", OWNER="$USER_NAME", MODE="0600", TAG+="uaccess"
RULES
sudo modprobe uinput
printf 'uinput\n' | sudo tee /etc/modules-load.d/faco-voicetype.conf >/dev/null
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=input || true
sudo udevadm trigger --name-match=uinput || true

mkdir -p "$USER_HOME/.config/systemd/user" "$USER_HOME/.config/autostart" "$USER_HOME/.local/share/applications"
YDOTOOL_USER_SERVICE="$USER_HOME/.config/systemd/user/ydotoold.service"
if ! systemctl --user is-active --quiet ydotoold.service 2>/dev/null && ! systemctl is-active --quiet ydotoold.service 2>/dev/null; then
  if [[ ! -e "$YDOTOOL_USER_SERVICE" ]]; then
    cat > "$YDOTOOL_USER_SERVICE" <<'SERVICE'
# FACO VoiceType managed service
[Unit]
Description=ydotool input injection daemon for FACO VoiceType
After=graphical-session.target
PartOf=graphical-session.target

[Service]
ExecStart=/usr/bin/ydotoold
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
SERVICE
  fi
fi
cat > "$AUTOSTART" <<EOF2
[Desktop Entry]
Type=Application
Name=FACO VoiceType
Comment=Global mouse-button voice-to-text
Exec="$APP_ROOT/run.sh"
Icon=audio-input-microphone
Terminal=false
X-GNOME-Autostart-enabled=true
StartupNotify=false
EOF2
cp "$AUTOSTART" "$DESKTOP_APP"
systemctl --user daemon-reload || true
[[ -f "$YDOTOOL_USER_SERVICE" ]] && systemctl --user enable --now ydotoold.service || true

cp "$APP_ROOT/faco_module.json" "$REGISTRY_ROOT/apps/voicetype.json"
cp "$APP_ROOT/faco_capabilities.json" "$REGISTRY_ROOT/capabilities/voicetype.json"

progress "Repair ownership and validate the deployed canonical source/runtime" "usually 10-30 seconds"
sudo chown -R "$USER_NAME:$USER_GROUP" "$APP_ROOT" "$STATE_ROOT" "$DATA_ROOT" "$ENV_ROOT" \
  "$REGISTRY_ROOT/apps/voicetype.json" "$REGISTRY_ROOT/capabilities/voicetype.json" \
  "$AUTOSTART" "$DESKTOP_APP"
[[ -f "$YDOTOOL_USER_SERVICE" ]] && sudo chown "$USER_NAME:$USER_GROUP" "$YDOTOOL_USER_SERVICE"
export FACO_RESOURCE_ROOT="$FACO_ROOT"
export FACO_VOICETYPE_APP_ROOT="$APP_ROOT"
export FACO_VOICETYPE_STATE_ROOT="$STATE_ROOT"
export FACO_VOICETYPE_DATA_ROOT="$DATA_ROOT"
export FACO_VOICETYPE_ENV_ROOT="$ENV_ROOT"
PYTHONPATH="$APP_ROOT/src" "$ENV_ROOT/bin/python" -m compileall -q "$APP_ROOT/src"
PYTHONPATH="$APP_ROOT/src" "$ENV_ROOT/bin/python" "$APP_ROOT/selftest.py"

progress "Remove obsolete heavyweight runtime duplication only after canonical validation passed" "a few seconds to a minute depending on old runtime size"
if (( COPIED_OLD_VENV )) && [[ -n "$OLD_VENV" && "$OLD_VENV" != "$ENV_ROOT" && -d "$OLD_VENV" ]]; then
  echo "Canonical runtime passed validation. Removing migrated legacy duplicate: $OLD_VENV"
  rm -rf -- "$OLD_VENV"
fi
if [[ -n "$OLD_TARGET" && "$OLD_TARGET" != "$APP_ROOT" && -d "$OLD_TARGET" ]]; then
  printf '%s\n' "$APP_ROOT" > "$OLD_TARGET/MIGRATED_TO_FACO_VoiceType.txt" 2>/dev/null || true
fi

progress "Installation complete; canonical paths and launch integration are active" "complete"
printf '\nFACO VoiceType v1.2.1 installed successfully.\n'
printf 'Canonical app : %s\n' "$APP_ROOT"
printf 'Persistent state: %s\n' "$STATE_ROOT"
printf 'Persistent data : %s\n' "$DATA_ROOT"
printf 'Shared runtime   : %s\n' "$ENV_ROOT"
printf 'Logs             : %s\n' "$LOG_DIR"
printf '\nThe installer terminal stays open by design.\n'
read -r -p 'Press Enter to launch FACO VoiceType from the canonical installation...' _
"$APP_ROOT/run.sh" || true
printf '\nFACO VoiceType has closed. Installer log: %s/install.log\n' "$LOG_DIR"
read -r -p 'Press Enter when you are ready to close this installer session...' _ || true

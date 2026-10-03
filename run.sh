#!/usr/bin/env bash
set -Eeuo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
FACO_ROOT="${FACO_RESOURCE_ROOT:-/media/owner/Faco Resources1}"
APP_ROOT="${FACO_VOICETYPE_APP_ROOT:-$FACO_ROOT/FACO/apps/voicetype}"
STATE_ROOT="${FACO_VOICETYPE_STATE_ROOT:-$FACO_ROOT/_state/apps/voicetype}"
DATA_ROOT="${FACO_VOICETYPE_DATA_ROOT:-$FACO_ROOT/_data/apps/voicetype}"
SHARED_ROOT="${FACO_SHARED_ROOT:-$FACO_ROOT/_shared}"
ENV_ROOT="${FACO_VOICETYPE_ENV_ROOT:-$SHARED_ROOT/environments/faco-voicetype}"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || printf '%s/Desktop' "$HOME")"
LOG_DIR="$DESKTOP_DIR/Logs/FACO VoiceType"
mkdir -p "$LOG_DIR" "$STATE_ROOT" "$DATA_ROOT"

# Running run.sh from an extracted release is a common human move. Redirect to
# the canonical installation instead of creating a second personality.
if [[ "$(readlink -f "$HERE")" != "$(readlink -f "$APP_ROOT" 2>/dev/null || printf '%s' "$APP_ROOT")" ]]; then
  if [[ -x "$APP_ROOT/run.sh" ]]; then
    exec "$APP_ROOT/run.sh" "$@"
  fi
  echo "FACO VoiceType is not installed in the canonical FACO location yet." >&2
  echo "Run: $HERE/install.sh" >&2
  exit 1
fi

if [[ ! -x "$ENV_ROOT/bin/python" ]]; then
  echo "FACO VoiceType canonical runtime is missing: $ENV_ROOT" >&2
  echo "Run: $APP_ROOT/install.sh" >&2
  exit 1
fi

export FACO_RESOURCE_ROOT="$FACO_ROOT"
export FACO_SHARED_ROOT="$SHARED_ROOT"
export FACO_VOICETYPE_APP_ROOT="$APP_ROOT"
export FACO_VOICETYPE_STATE_ROOT="$STATE_ROOT"
export FACO_VOICETYPE_DATA_ROOT="$DATA_ROOT"
export FACO_VOICETYPE_ENV_ROOT="$ENV_ROOT"

if [[ -z "${YDOTOOL_SOCKET:-}" ]]; then
  if [[ -S "/run/user/$(id -u)/.ydotool_socket" ]]; then
    export YDOTOOL_SOCKET="/run/user/$(id -u)/.ydotool_socket"
  elif [[ -S /tmp/.ydotool_socket ]]; then
    export YDOTOOL_SOCKET=/tmp/.ydotool_socket
  fi
fi

CUDA_PATH_FILE="$STATE_ROOT/cuda_lib_paths"
if [[ -s "$CUDA_PATH_FILE" ]]; then
  SHARED_CUDA_LIBS="$(cat "$CUDA_PATH_FILE")"
  export LD_LIBRARY_PATH="$SHARED_CUDA_LIBS${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

# Fall back to NVIDIA wheels already inside the canonical environment.
CUDA_PY_LIBS="$($ENV_ROOT/bin/python - <<'PY' 2>/dev/null || true
import importlib.util
import os
paths=[]
for modname in ('nvidia.cublas.lib','nvidia.cudnn.lib'):
    try:
        spec=importlib.util.find_spec(modname)
        if spec is None:
            continue
        if spec.submodule_search_locations:
            paths.extend(str(p) for p in spec.submodule_search_locations)
        elif spec.origin:
            paths.append(os.path.dirname(spec.origin))
    except Exception:
        pass
print(':'.join(dict.fromkeys(paths)))
PY
)"
if [[ -n "$CUDA_PY_LIBS" ]]; then
  export LD_LIBRARY_PATH="$CUDA_PY_LIBS${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

export PYTHONPATH="$APP_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$ENV_ROOT/bin/python" -m faco_voicetype "$@" >>"$LOG_DIR/launcher.log" 2>&1

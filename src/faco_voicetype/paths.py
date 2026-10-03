from __future__ import annotations

import os
from pathlib import Path

APP_SLUG = "voicetype"
DEFAULT_FACO_ROOT = Path("/media/owner/Faco Resources1")


def faco_root() -> Path:
    raw = os.environ.get("FACO_RESOURCE_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser()
    return DEFAULT_FACO_ROOT


def app_root() -> Path:
    raw = os.environ.get("FACO_VOICETYPE_APP_ROOT", "").strip()
    return Path(raw).expanduser() if raw else faco_root() / "FACO" / "apps" / APP_SLUG


def state_root() -> Path:
    raw = os.environ.get("FACO_VOICETYPE_STATE_ROOT", "").strip()
    return Path(raw).expanduser() if raw else faco_root() / "_state" / "apps" / APP_SLUG


def data_root() -> Path:
    raw = os.environ.get("FACO_VOICETYPE_DATA_ROOT", "").strip()
    return Path(raw).expanduser() if raw else faco_root() / "_data" / "apps" / APP_SLUG


def shared_root() -> Path:
    raw = os.environ.get("FACO_SHARED_ROOT", "").strip()
    return Path(raw).expanduser() if raw else faco_root() / "_shared"


def environment_root() -> Path:
    raw = os.environ.get("FACO_VOICETYPE_ENV_ROOT", "").strip()
    return Path(raw).expanduser() if raw else shared_root() / "environments" / "faco-voicetype"


def ensure_runtime_dirs() -> None:
    for path in (state_root(), data_root()):
        path.mkdir(parents=True, exist_ok=True)

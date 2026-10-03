from __future__ import annotations

import logging
import os
from pathlib import Path
from logging.handlers import RotatingFileHandler

APP_NAME = "FACO VoiceType"


def desktop_dir() -> Path:
    """Resolve the user's real desktop path without assuming ~/Desktop."""
    try:
        import subprocess
        out = subprocess.check_output(["xdg-user-dir", "DESKTOP"], text=True, stderr=subprocess.DEVNULL).strip()
        if out:
            return Path(os.path.expandvars(out)).expanduser()
    except Exception:
        pass
    return Path.home() / "Desktop"


def log_dir() -> Path:
    path = desktop_dir() / "Logs" / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def setup_logging() -> Path:
    target = log_dir() / "current.log"
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        handler = RotatingFileHandler(target, maxBytes=4_000_000, backupCount=5, encoding="utf-8")
        handler.setFormatter(fmt)
        root.addHandler(handler)
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)
    logging.getLogger(__name__).info("Logging initialized: %s", target)
    return target

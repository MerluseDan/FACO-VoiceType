#!/usr/bin/env python3
"""Tiny stdlib-only launcher for user service startup and optional late mounts.

The launcher lives in the XDG config directory so systemd can start it
even when the optional user-selected external storage is unavailable.
"""
import json
import os
from pathlib import Path
import signal
import sys
import threading

CONFIG = Path(os.environ.get('FACO_WATCH_CONFIG_DIR') or (Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'faco-resource-watch')) / 'startup.json'
POLL_SECONDS = 4.0
_stop = threading.Event()


def _halt(signum, frame):
    _stop.set()


def installation_ready(config_path=CONFIG):
    """Return (entrypoint, reason). Never construct an app folder on a missing disk."""
    try:
        settings = json.loads(Path(config_path).read_text(encoding='utf-8'))
        install = Path(settings['install_dir']).expanduser()
        mounts = settings.get('require_mounts', [])
        if not isinstance(mounts, list):
            return None, 'Invalid required mounts in startup configuration'
        if settings.get('require_mount'):
            mounts.append(settings['require_mount'])
        if not install.is_absolute():
            return None, 'Invalid relative installation path in startup configuration'
        for mount_root in mounts:
            mount_root = Path(mount_root)
            if not mount_root.is_absolute():
                return None, 'Invalid mount path in startup configuration'
            if not mount_root.is_mount():
                return None, f'Waiting for user-selected storage to mount: {mount_root}'
        entry = install / 'bin' / 'faco-resource-watch'
        if not entry.is_file() or not (install / 'faco_watch' / 'cli.py').is_file():
            return None, f'Waiting for installed application: {install}'
        return entry, ''
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, f'Waiting for startup configuration: {exc}'


def main():
    signal.signal(signal.SIGTERM, _halt)
    signal.signal(signal.SIGINT, _halt)
    last_message = None
    while not _stop.is_set():
        path, reason = installation_ready()
        if path is not None:
            print(f'FACO Resource Watch: starting background collector from {path}', flush=True)
            # Replace the shim with the real collector. systemd monitors the same
            # PID; Restart=always covers unexpected collector exits or kills.
            os.execv(sys.executable, [sys.executable, str(path), 'serve'])
        if reason != last_message:
            print(f'FACO Resource Watch: {reason}', flush=True)
            last_message = reason
        _stop.wait(POLL_SECONDS)
    return 0


if __name__ == '__main__':
    sys.exit(main())

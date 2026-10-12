"""Linux XDG directories. Executable code is separate from persistent data."""
import json
import os
from pathlib import Path

APP = 'faco-resource-watch'


def xdg(name, default):
    value = os.environ.get(name)
    if value and Path(value).is_absolute():
        return Path(value)
    return Path.home() / default


CONFIG = Path(os.environ['FACO_WATCH_CONFIG_DIR']) if (
    os.environ.get('FACO_WATCH_CONFIG_DIR') and Path(os.environ['FACO_WATCH_CONFIG_DIR']).is_absolute()
) else xdg('XDG_CONFIG_HOME', '.config') / APP
RUNTIME = xdg('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}') / APP
DATA_HOME = xdg('XDG_DATA_HOME', '.local/share') / APP
STATE_HOME = xdg('XDG_STATE_HOME', '.local/state') / APP
INSTALL_DIR = Path(__file__).resolve().parent.parent


def _config_paths():
    config = CONFIG / 'paths.json'
    if config.is_file():
        try:
            return json.loads(config.read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError):
            pass
    return {}


def data_dir():
    override = os.environ.get('FACO_WATCH_DATA_DIR')
    if override and Path(override).expanduser().is_absolute():
        return Path(override).expanduser()
    configured = _config_paths().get('data_dir')
    if isinstance(configured, str) and Path(configured).is_absolute():
        return Path(configured)
    return DATA_HOME / 'data'


def db_path():
    return data_dir() / 'history.sqlite3'


def logs_dir():
    configured = _config_paths().get('logs_dir')
    if isinstance(configured, str) and Path(configured).is_absolute():
        return Path(configured)
    return STATE_HOME / 'logs'


def current_path():
    return RUNTIME / 'latest.json'


def source_web():
    return INSTALL_DIR / 'web'

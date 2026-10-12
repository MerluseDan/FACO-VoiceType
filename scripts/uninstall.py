#!/usr/bin/env python3
"""Remove user integration and code while preserving history unless requested."""
import os
from pathlib import Path
import shutil
import sys

from install import APP, UUID, call, read_json, resolve_paths, safe_path_from_settings


def uninstall(purge=False):
    p = resolve_paths()
    old = read_json(p['startup'])
    prefs = read_json(p['paths'])
    installed = safe_path_from_settings(old.get('install_dir')) or p['default_install']
    data = safe_path_from_settings(prefs.get('data_dir')) or p['default_data']
    logs = safe_path_from_settings(prefs.get('logs_dir')) or p['default_logs']
    if shutil.which('systemctl'):
        call(['systemctl', '--user', 'disable', '--now', 'faco-resource-watch.service'])
    p['service'].unlink(missing_ok=True)
    p['agent'].unlink(missing_ok=True)
    p['startup'].unlink(missing_ok=True)
    if shutil.which('systemctl'):
        call(['systemctl', '--user', 'daemon-reload'])
    if shutil.which('gnome-extensions'):
        call(['gnome-extensions', 'disable', UUID])
    if p['extension'].exists():
        shutil.rmtree(p['extension'])
    p['desktop'].unlink(missing_ok=True)
    p['icon'].unlink(missing_ok=True)
    # Never delete a launcher that belongs to an unrelated program.
    if p['launcher'].is_symlink():
        target = p['launcher'].resolve(strict=False)
        if target == installed / 'bin/faco-resource-watch':
            p['launcher'].unlink()
    if installed.is_dir() and (installed / '.faco-resource-watch-installed').is_file():
        shutil.rmtree(installed)
        print(f'Application code removed: {installed}')
    else:
        print(f'Skipped removal of unrecognized application folder: {installed}')
    if purge:
        # Only remove the app-owned database files, never recursively wipe an
        # arbitrary custom path that might contain unrelated user files.
        for name in ('history.sqlite3', 'history.sqlite3-wal', 'history.sqlite3-shm'):
            (data / name).unlink(missing_ok=True)
        if logs.is_dir():
            for file in logs.glob('*collector.log*'):
                if file.is_file() and not file.is_symlink():
                    file.unlink()
        p['paths'].unlink(missing_ok=True)
        print(f'Historical database files purged: {data}')
    else:
        print(f'History and logs preserved: {data} | {logs}')
    # Deliberately never disable loginctl linger: it is account-wide.
    runtime = Path(os.environ.get('XDG_RUNTIME_DIR') or (f'/run/user/{os.getuid()}')) / APP
    (runtime / 'latest.json').unlink(missing_ok=True)
    print('FACO Resource Watch background service and GNOME indicator removed.')


if __name__ == '__main__':
    try:
        uninstall(purge='--purge-data' in sys.argv[1:])
    except (OSError, RuntimeError, shutil.Error) as exc:
        print(f'Uninstall failed: {exc}', file=sys.stderr)
        sys.exit(1)

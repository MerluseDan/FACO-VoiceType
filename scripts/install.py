#!/usr/bin/env python3
"""Portable, dependency-free XDG installer for FACO Resource Watch.

Fresh installations never probe or select a developer-specific volume. Existing
legacy data is backed up with SQLite before the startup configuration changes.
"""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile

APP = 'faco-resource-watch'
LEGACY_NAME = 'FACO_Resource_Watch'
UUID = 'faco-resource-watch@faco.local'
SOURCE = Path(__file__).resolve().parent.parent


def base_dir(variable, fallback):
    candidate = os.environ.get(variable, '').strip()
    if candidate and Path(candidate).is_absolute():
        return Path(candidate).expanduser()
    return Path.home() / fallback


def resolve_paths():
    home = Path.home()
    data_home = base_dir('XDG_DATA_HOME', '.local/share')
    config_home = base_dir('XDG_CONFIG_HOME', '.config')
    state_home = base_dir('XDG_STATE_HOME', '.local/state')
    app_home = data_home / APP
    return dict(home=home, data_home=data_home, config_home=config_home,
                state_home=state_home, default_install=app_home / 'app',
                default_data=app_home / 'data', default_logs=state_home / APP / 'logs',
                cfg=config_home / APP, service=config_home / 'systemd/user/faco-resource-watch.service',
                agent=config_home / APP / 'boot_agent.py',
                startup=config_home / APP / 'startup.json',
                paths=config_home / APP / 'paths.json',
                launcher=home / '.local/bin/faco-resource-watch',
                desktop=data_home / 'applications/faco-resource-watch.desktop',
                extension=data_home / 'gnome-shell/extensions' / UUID,
                icon=data_home / 'icons/hicolor/scalable/apps/faco-resource-watch.svg')


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return {}


def safe_path_from_settings(value):
    if not value or not isinstance(value, str):
        return None
    value = Path(value).expanduser()
    return value if value.is_absolute() else None


def previous_data(paths):
    old_start = read_json(paths['startup'])
    old_config = read_json(paths['paths'])
    old_install = safe_path_from_settings(old_start.get('install_dir'))
    old_data = safe_path_from_settings(old_config.get('data_dir'))
    if old_data is None and old_install is not None:
        old_data = old_install / 'data'
    old_logs = safe_path_from_settings(old_config.get('logs_dir'))
    if old_logs is None and old_install is not None:
        old_logs = old_install / '_logs'
    return old_install, old_data, old_logs


def is_removable_location(path):
    # Guard any location under common Linux mount-root directories, without
    # embedding developer usernames or machine-specific drive names.
    real = Path(os.path.abspath(str(path)))
    parts = real.parts
    return (len(parts) > 2 and parts[1] in ('media', 'mnt')) or (
        len(parts) > 3 and parts[1:3] == ('run', 'media'))


def mounted_parent(path):
    path = Path(os.path.abspath(str(path)))
    search = path
    while not search.exists() and search != search.parent:
        search = search.parent
    while search != search.parent:
        if search.is_mount():
            return search
        search = search.parent
    return None


def validate_custom(path, label):
    """Require an existing, writable parent, and a real mount under /media/mnt."""
    if not path.is_absolute() or path == Path('/'):
        return None, f'{label} must be an absolute directory path.'
    if path.is_symlink():
        return None, f'{label} may not be a symbolic link.'
    if path.exists() and not path.is_dir():
        return None, f'{label} points to a file, not a directory.'
    # Require the immediate parent, not merely a distant writable ancestor:
    # otherwise a missing mounted drive could be created on the root disk.
    parent = path.parent
    if not parent.is_dir() or not os.access(parent, os.W_OK | os.X_OK):
        return None, f'{label} parent is not a writable directory: {parent}'
    mount = mounted_parent(path)
    if is_removable_location(path):
        if mount is None:
            return None, f'{label} requires a mounted drive at {path}; no mounted parent found.'
        # A path immediately underneath /media, /mnt, /run/media is usually a
        # missing device path. Do not accept a mount of the mount-root itself.
        if mount in (Path('/media'), Path('/mnt'), Path('/run/media')):
            return None, f'{label} requires a mounted device, not just {mount}.'
    # Record mounts for custom locations regardless of their absolute path;
    # an explicitly selected mounted volume under /srv or /home must also be
    # checked by the boot agent and history layer.
    return mount, None


def missing_location_message(description, path):
    print(f'\n[Storage] {description} is unavailable: {path}', file=sys.stderr)
    print('[Storage] Choose: 1) Use OS Default Location  2) Cancel Installation', file=sys.stderr)
    choose = os.environ.get('FACO_WATCH_MISSING_CUSTOM', '').strip().lower()
    if choose in ('default', '1'):
        print('[Storage] Explicit choice: Use OS Default Location.')
        return True
    if not os.environ.get('FACO_INSTALL_NONINTERACTIVE') and sys.stdin.isatty():
        try:
            return input('Enter 1 for OS Default Location, otherwise cancel [2]: ').strip() == '1'
        except EOFError:
            return False
    return False


def atomic_json(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix='.'+path.name+'.', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(contents, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(filename, 0o600)
        os.replace(filename, path)
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


def call(cmd, quiet=True):
    try:
        return subprocess.run(cmd, stdin=subprocess.DEVNULL, check=False,
                              stdout=subprocess.DEVNULL if quiet else None,
                              stderr=subprocess.DEVNULL if quiet else None).returncode == 0
    except (OSError, ValueError):
        return False


def migrate_history(old_data, new_data):
    if old_data is None or old_data == new_data:
        return 'No previous database migration needed.'
    src = old_data / 'history.sqlite3'
    dst = new_data / 'history.sqlite3'
    if dst.exists():
        return 'Destination database already exists; retained without overwriting.'
    if not src.is_file():
        return 'No previous database found to migrate.'
    new_data.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix='.faco-history-', suffix='.sqlite3', dir=str(new_data))
    os.close(fd)
    try:
        with sqlite3.connect(f'file:{src}?mode=ro', uri=True, timeout=15) as source:
            with sqlite3.connect(filename) as target:
                source.backup(target, pages=256, sleep=0.05)
                result = target.execute('PRAGMA quick_check').fetchone()
                if result is None or result[0] != 'ok':
                    raise RuntimeError(f'Historical database integrity check failed: {result}')
        os.chmod(filename, 0o600)
        os.replace(filename, dst)
        return f'Preserved existing history with verified SQLite backup from {src}.'
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


def migrate_logs(old_logs, new_logs):
    if old_logs is None or old_logs == new_logs or not old_logs.is_dir():
        return
    new_logs.mkdir(parents=True, exist_ok=True)
    for file in old_logs.iterdir():
        if file.is_file() and not file.is_symlink() and file.name.startswith('collector.log'):
            target = new_logs / ('legacy-' + file.name)
            if not target.exists():
                shutil.copy2(file, target)


def write_service(paths):
    # systemd expands %, so escape it for literal paths; quote spaces.
    agent = str(paths['agent']).replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"')
    config = str(paths['cfg']).replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"')
    contents = f'''[Unit]
Description=FACO Resource Watch (local resource history)
StartLimitIntervalSec=0

[Service]
Type=simple
ExecStart=/usr/bin/python3 "{agent}"
Environment="FACO_WATCH_CONFIG_DIR={config}"
Environment=PYTHONDONTWRITEBYTECODE=1
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
'''
    paths['service'].parent.mkdir(parents=True, exist_ok=True)
    paths['service'].write_text(contents, encoding='utf-8')
    paths['service'].chmod(0o644)


def install():
    p = resolve_paths()
    print('\nFACO RESOURCE WATCH 1.0.3 | PUBLIC PORTABLE INSTALLER')
    print('=====================================================')
    for needed in ('faco_watch/cli.py', 'web/index.html', 'scripts/boot_agent.py', 'bin/faco-resource-watch'):
        if not (SOURCE / needed).is_file():
            raise RuntimeError(f'Package incomplete: missing {needed}. Extract the entire ZIP.')
    if sys.version_info < (3, 9):
        raise RuntimeError(f'Python 3.9 or newer required (found {sys.version.split()[0]}).')
    if sys.platform != 'linux':
        raise RuntimeError('This release targets Linux; no system changes made.')
    prev_install, prev_data, prev_logs = previous_data(p)
    install_dir, data_dir = p['default_install'], p['default_data']
    required_mounts = []
    for key, label in [('FACO_WATCH_INSTALL_DIR', 'Custom install location'),
                       ('FACO_WATCH_DATA_DIR', 'Custom history location')]:
        choice = os.environ.get(key)
        if choice:
            target = Path(choice).expanduser()
            mount, error = validate_custom(target, label)
            if error:
                if not missing_location_message(error, target):
                    raise RuntimeError(f'Cancelled: {label} inaccessible. Nothing was installed.')
                continue
            if key == 'FACO_WATCH_INSTALL_DIR':
                install_dir = target
            else:
                data_dir = target
            if mount is not None and str(mount) not in required_mounts:
                required_mounts.append(str(mount))
    if prev_install is not None and prev_install != install_dir and (
            not prev_install.exists() or (is_removable_location(prev_install) and mounted_parent(prev_install) is None)):
        # An older app lived on a custom/missing location. A clean OS-default
        # install would be possible but would not contain its unmounted history.
        if not missing_location_message('Previously configured install location', prev_install):
            raise RuntimeError('Cancelled to protect history on the unavailable drive.')
        prev_data = None
        prev_logs = None
    if prev_data is not None and prev_data != data_dir and (
            not prev_data.exists() or (is_removable_location(prev_data) and mounted_parent(prev_data) is None)):
        if not missing_location_message('Previously configured history location', prev_data):
            raise RuntimeError('Cancelled to protect previous historical data.')
        prev_data = None
        prev_logs = None
    # Refuse conflicts before stopping services or moving files.
    if p['launcher'].exists() and not p['launcher'].is_symlink():
        raise RuntimeError(f'Existing launcher is not ours: {p["launcher"]}')
    if p['launcher'].is_symlink():
        actual = p['launcher'].resolve(strict=False)
        allowed = [install_dir / 'bin/faco-resource-watch']
        if prev_install is not None:
            allowed.append(prev_install / 'bin/faco-resource-watch')
        if actual not in allowed:
            raise RuntimeError(f'Existing launcher targets a different application: {actual}')
    print(f'[Paths] Application : {install_dir}')
    print(f'[Paths] History     : {data_dir}')
    print(f'[Paths] Settings    : {p["cfg"]}')
    print(f'[Paths] Logs        : {p["default_logs"]}')
    print(f'[Paths] Custom mounts: {", ".join(required_mounts) if required_mounts else "None"}')
    print('[1/5] Stopping old user service before SQLite backup...')
    if shutil.which('systemctl'):
        call(['systemctl', '--user', 'stop', 'faco-resource-watch.service'])
    data_dir.mkdir(parents=True, exist_ok=True)
    p['default_logs'].mkdir(parents=True, exist_ok=True)
    data_dir.chmod(0o700)
    p['default_logs'].chmod(0o700)
    print('[2/5]', migrate_history(prev_data, data_dir))
    migrate_logs(prev_logs, p['default_logs'])
    install_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.faco-watch-stage-', dir=str(install_dir.parent)))
    old_backup = None
    try:
        for item in ('faco_watch', 'web', 'extension', 'bin', 'scripts'):
            shutil.copytree(SOURCE / item, stage / item, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'publish_github.sh'))
        for item in ('install.sh', 'run.sh', 'uninstall.sh', 'verify.sh', 'README.md', 'LICENSE'):
            shutil.copy2(SOURCE / item, stage / item)
        (stage / '.faco-resource-watch-installed').write_text('FACO Resource Watch portable installation\n')
        (stage / 'bin/faco-resource-watch').chmod(0o755)
        for item in ('install.sh', 'run.sh', 'uninstall.sh', 'verify.sh'):
            (stage / item).chmod(0o755)
        if install_dir.exists():
            old_backup = install_dir.parent / ('.faco-watch-previous-' + str(os.getpid()))
            if old_backup.exists():
                raise RuntimeError(f'Previous install backup already exists: {old_backup}')
            install_dir.rename(old_backup)
        stage.rename(install_dir)
    except Exception:
        if old_backup is not None and old_backup.is_dir() and not install_dir.exists():
            old_backup.rename(install_dir)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    if old_backup is not None and old_backup.exists():
        shutil.rmtree(old_backup)
    # Standard user entry points. Default is always the Linux XDG location;
    # a custom location is used only if explicitly requested.
    p['launcher'].parent.mkdir(parents=True, exist_ok=True)
    if p['launcher'].exists() and not p['launcher'].is_symlink():
        raise RuntimeError(f'An unrelated executable already occupies {p["launcher"]}. Not replacing it.')
    if p['launcher'].is_symlink():
        current_target = p['launcher'].resolve(strict=False)
        if current_target != install_dir / 'bin/faco-resource-watch' and (
                prev_install is None or current_target != prev_install / 'bin/faco-resource-watch'):
            raise RuntimeError(f'Launcher symlink is owned by a different application: {p["launcher"]}')
        p['launcher'].unlink()
    p['launcher'].symlink_to(install_dir / 'bin/faco-resource-watch')
    p['extension'].mkdir(parents=True, exist_ok=True)
    shutil.copytree(install_dir / 'extension' / UUID, p['extension'], dirs_exist_ok=True)
    p['icon'].parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(install_dir / 'web/favicon.svg', p['icon'])
    p['desktop'].parent.mkdir(parents=True, exist_ok=True)
    # The desktop entry calls the fixed standard launcher; the actual install
    # directory may contain spaces or be on a custom drive.
    quoted = str(p['launcher']).replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$')
    p['desktop'].write_text(f'''[Desktop Entry]
Type=Application
Name=FACO Resource Watch
Comment=Live Linux system resources and historical charts
Exec="{quoted}" open
Icon=faco-resource-watch
Terminal=false
Categories=System;Monitor;
StartupNotify=true
''', encoding='utf-8')
    p['desktop'].chmod(0o644)
    p['cfg'].mkdir(parents=True, exist_ok=True)
    shutil.copy2(install_dir / 'scripts/boot_agent.py', p['agent'])
    p['agent'].chmod(0o700)
    atomic_json(p['paths'], dict(data_dir=str(data_dir), logs_dir=str(p['default_logs'])))
    atomic_json(p['startup'], dict(install_dir=str(install_dir), require_mounts=required_mounts))
    write_service(p)
    print('[3/5] Installed GNOME indicator, XDG launcher, and user service.')
    if shutil.which('systemctl'):
        if call(['systemctl', '--user', 'daemon-reload']) and call(
                ['systemctl', '--user', 'enable', '--now', 'faco-resource-watch.service']):
            print('[4/5] Background collector enabled at login; service auto-restart configured.')
        else:
            print('[4/5] User systemd unavailable; enable on desktop with:')
            print('      systemctl --user enable --now faco-resource-watch.service')
    else:
        print('[4/5] systemctl unavailable; background service needs manual setup.')
    if shutil.which('loginctl'):
        user = os.environ.get('USER') or Path.home().name
        show = subprocess.run(['loginctl', 'show-user', user, '--property=Linger', '--value'],
                              capture_output=True, text=True, check=False)
        if show.stdout.strip() == 'yes':
            print('[Boot] Startup before login and persistence after logout already enabled.')
        elif call(['loginctl', 'enable-linger', user]):
            print('[Boot] Enabled service at boot, before desktop login.')
        else:
            print('[Boot] Service starts on login; pre-login start needs authorization:')
            print(f'       sudo loginctl enable-linger {user}')
    if shutil.which('gnome-extensions'):
        if call(['gnome-extensions', 'enable', UUID]):
            print('[5/5] GNOME clock-side indicator enabled.')
        else:
            print('[5/5] GNOME indicator installed. Log out/in, then enable with:')
            print(f'      gnome-extensions enable {UUID}')
    else:
        print('[5/5] GNOME not detected. Dashboard remains available via launcher.')
    print('\nINSTALLATION COMPLETE')
    print(f'Launcher : {p["launcher"]} open')
    print(f'History  : {data_dir}/history.sqlite3')
    print(f'Logs     : {p["default_logs"]}')
    print(f'Uninstall: {install_dir}/uninstall.sh')
    # Doctor is advisory: CPU sensor or NVIDIA hardware may be absent here.
    call([str(p['launcher']), 'doctor'], quiet=False)


if __name__ == '__main__':
    try:
        install()
    except (OSError, RuntimeError, sqlite3.Error, shutil.Error) as exc:
        print(f'INSTALLATION FAILED: {exc}', file=sys.stderr)
        sys.exit(1)

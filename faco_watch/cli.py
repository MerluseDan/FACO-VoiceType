"""CLI entry point used by systemd, installer, and GNOME indicator."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
from . import storage
from .collector import CpuSampler, cpu_temperature, memory_stats
from .gpu import GpuSampler
from .paths import current_path, db_path, data_dir, INSTALL_DIR
from .server import PORT


def health():
    output = {'program': 'FACO Resource Watch', 'version': '1.0.3',
              'storage': str(data_dir()), 'db': str(db_path()),
              'system': {}, 'checks': []}
    def add(name, status, detail):
        output['checks'].append({'component': name, 'status': status, 'detail': str(detail)})
    add('Python runtime', 'Passed' if sys.version_info >= (3, 9) else 'Blocked', sys.version.split()[0])
    ram = memory_stats()
    add('Linux CPU/RAM', 'Passed' if ram['total_bytes'] else 'Blocked',
        f"Total RAM: {round((ram['total_bytes'] or 0)/1024**3, 1)} GiB")
    temp = cpu_temperature()
    add('CPU temperature', 'Passed' if temp is not None else 'Needs Testing',
        f'{temp} °C' if temp is not None else 'No readable CPU sensor found; shown as —')
    try:
        db = storage.connect()
        db.execute('SELECT COUNT(*) FROM samples').fetchone()
        db.close()
        add('History database', 'Passed', str(db_path()))
    except Exception as exc:
        add('History database', 'Blocked', repr(exc))
    gpu = GpuSampler().sample()
    add('NVIDIA GPU', 'Passed' if gpu['gpus'] else 'Needs Testing',
        ', '.join(g['name'] for g in gpu['gpus']) or gpu.get('error') or 'No GPU detected')
    if gpu['gpus']:
        add('GPU process attribution',
            'Passed' if gpu['gpus'][0].get('process_list_supported') else 'Needs Testing',
            'NVML process context listing' if gpu['gpus'][0].get('process_list_supported')
            else 'Driver/backend did not provide process list')
    shell = shutil.which('gnome-shell')
    output['system']['gnome_shell'] = None
    if shell:
        try:
            ver = subprocess.run([shell, '--version'], capture_output=True, text=True, timeout=3)
            output['system']['gnome_shell'] = (ver.stdout + ver.stderr).strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    add('GNOME panel extension', 'Needs Testing',
        output['system']['gnome_shell'] or 'GNOME Shell unavailable in this environment')
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/api/health', timeout=1) as r:
            info = json.load(r)
        same_install = info.get('install_path') == str(INSTALL_DIR.resolve())
        api_live = info.get('ok', False) and same_install
        add('Background service', 'Passed' if api_live else 'Needs Repair',
            'Correct installation responding on loopback' if api_live else
            f"Port used by different service/install: {info.get('install_path', 'unknown')}")
    except Exception:
        add('Background service', 'Needs Testing', 'Not running; start with systemctl --user')
    # Separate the GUI from the boot-time user service: stopping Chrome must
    # not affect sampler persistence. "linger" is required before *login*.
    systemctl = shutil.which('systemctl')
    if systemctl:
        try:
            enabled = subprocess.run([systemctl, '--user', 'is-enabled',
                                      'faco-resource-watch.service'],
                                     capture_output=True, text=True, timeout=3)
            add('Login startup', 'Passed' if enabled.returncode == 0 else 'Needs Testing',
                enabled.stdout.strip() or 'Unable to confirm enabled user service')
        except (OSError, subprocess.TimeoutExpired):
            add('Login startup', 'Needs Testing', 'Unable to check user service')
    loginctl = shutil.which('loginctl')
    if loginctl:
        try:
            linger = subprocess.run([loginctl, 'show-user', str(os.getuid()),
                                     '--property=Linger', '--value'],
                                    capture_output=True, text=True, timeout=3)
            value = linger.stdout.strip()
            add('OS boot / post-logout', 'Passed' if linger.returncode == 0 and value == 'yes'
                else 'Needs Testing',
                'systemd lingering enabled' if linger.returncode == 0 and value == 'yes'
                else 'Boot-before-login may require: sudo loginctl enable-linger $(id -un)')
        except (OSError, subprocess.TimeoutExpired):
            add('OS boot / post-logout', 'Needs Testing', 'Unable to check lingering')
    output['ready'] = not any(c['status'] in ('Blocked', 'Needs Repair') for c in output['checks'])
    return output


def open_gui():
    url = f'http://127.0.0.1:{PORT}/'
    def matching_service():
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{PORT}/api/health', timeout=1) as r:
                reply = json.load(r)
            return reply.get('service') == 'FACO Resource Watch' and (
                reply.get('install_path') == str(INSTALL_DIR.resolve()))
        except Exception:
            return False
    if not matching_service():
        if shutil.which('systemctl'):
            try:
                subprocess.run(['systemctl', '--user', 'restart', 'faco-resource-watch.service'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6)
            except (OSError, subprocess.TimeoutExpired):
                pass
        for _ in range(12):
            if matching_service():
                break
            time.sleep(0.25)
        else:
            print('FACO collector is not available, or localhost port 18777 is owned by',
                  'another installation. Run: faco-resource-watch doctor', file=sys.stderr)
            return 1
    # Chrome --app opens a self-contained GUI; fallback is the default browser.
    for binary in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser'):
        app = shutil.which(binary)
        if app:
            subprocess.Popen([app, f'--app={url}', '--new-window'],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return 0
    opener = shutil.which('xdg-open')
    if opener:
        subprocess.Popen([opener, url], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return 0
    print(f'Open {url} in your browser.')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='FACO Resource Watch background Linux monitor')
    parser.add_argument('command', nargs='?', default='open',
                        choices=['open', 'serve', 'doctor', 'once', 'status'])
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--port', type=int, default=PORT)
    args = parser.parse_args(argv)
    if args.command == 'open':
        return open_gui()
    if args.command == 'serve':
        from .service import serve
        serve(args.port)
        return 0
    if args.command == 'doctor':
        diag = health()
        if args.json:
            print(json.dumps(diag, indent=2))
        else:
            for c in diag['checks']:
                print(f"{c['status']:16} {c['component']}: {c['detail']}")
        return 0 if diag['ready'] else 2
    if args.command == 'status':
        try:
            snap = json.loads(current_path().read_text(encoding='utf-8'))
            snap['age_seconds'] = max(0, int(time.time()) - int(snap['ts']))
            print(json.dumps(snap, indent=2))
            return 0
        except Exception:
            print('No current sample; service may not be running.', file=sys.stderr)
            return 1
    cpu = CpuSampler()
    cpu.sample()
    time.sleep(0.25)
    snap = {'cpu_percent': cpu.sample(), 'ram': memory_stats(),
            'cpu_temp_c': cpu_temperature()}
    snap.update(GpuSampler().sample())
    print(json.dumps(snap, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())

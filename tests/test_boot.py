"""Boot, delayed-mount and separate-daemon regression checks for 1.0.3."""
import json
import os
import select
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import boot_agent


class BootAgentTests(unittest.TestCase):
    def write_cfg(self, base, install, mount=None):
        path = Path(base) / 'startup.json'
        path.write_text(json.dumps({'install_dir': str(install),
                                    'require_mount': mount}), encoding='utf-8')
        return path

    def test_missing_config_or_install_never_creates_app_data(self):
        with tempfile.TemporaryDirectory() as d:
            install = Path(d) / 'unmounted' / 'Apps' / 'FACO_Resource_Watch'
            empty = Path(d) / 'missing-config.json'
            entry, msg = boot_agent.installation_ready(empty)
            self.assertIsNone(entry)
            self.assertIn('Waiting', msg)
            cfg = self.write_cfg(d, install)
            entry, msg = boot_agent.installation_ready(cfg)
            self.assertIsNone(entry)
            self.assertFalse(install.exists(), 'Boot must not create mountpoint data')

    def test_external_drive_waits_for_mount_even_with_stale_app_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            install = root / 'Apps' / 'FACO_Resource_Watch'
            (install / 'bin').mkdir(parents=True)
            (install / 'faco_watch').mkdir(parents=True)
            (install / 'bin' / 'faco-resource-watch').write_text('#!python\n')
            (install / 'faco_watch' / 'cli.py').write_text('# tests\n')
            cfg = self.write_cfg(d, install, str(root))
            with mock.patch('pathlib.Path.is_mount', return_value=False):
                entry, msg = boot_agent.installation_ready(cfg)
            self.assertIsNone(entry)
            self.assertIn('Waiting for user-selected storage', msg)
            with mock.patch('pathlib.Path.is_mount', return_value=True):
                entry, msg = boot_agent.installation_ready(cfg)
            self.assertEqual(entry, install / 'bin' / 'faco-resource-watch')

    def test_rejects_nonabsolute_paths(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIn('Invalid relative installation path',
                          boot_agent.installation_ready(self.write_cfg(d,'relative'))[1])
            self.assertIn('Invalid mount path',
                          boot_agent.installation_ready(self.write_cfg(d, d, 'relative'))[1])

    def test_agent_stops_cleanly_while_waiting_for_unmounted_drive(self):
        with tempfile.TemporaryDirectory() as d:
            env=dict(os.environ, HOME=str(Path(d)),
                     FACO_WATCH_CONFIG_DIR=str(Path(d)/'.config/faco-resource-watch'),
                     PYTHONDONTWRITEBYTECODE='1')
            process=subprocess.Popen([sys.executable, str(ROOT/'scripts/boot_agent.py')],
                                     env=env,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL, text=True)
            try:
                ready,_,_ = select.select([process.stdout], [], [], 5)
                self.assertTrue(ready, 'Boot agent did not report waiting state')
                self.assertIn('Waiting',process.stdout.readline())
                self.assertIsNone(process.poll())
                process.terminate()
                self.assertEqual(process.wait(timeout=3),0)
                self.assertEqual(list(Path(d).iterdir()),[])
            finally:
                if process.poll() is None:process.kill();process.wait(timeout=3)
                process.stdout.close()

    def test_boot_agent_wait_then_execs_real_worker_same_pid(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            cfgdir = home / '.config' / 'faco-resource-watch'
            cfgdir.mkdir(parents=True)
            install = home / 'installed'
            (cfgdir / 'startup.json').write_text(json.dumps({'install_dir':str(install),
                                                             'require_mount':None}))
            marker = home / 'boot-worker-ran.json'
            env = dict(os.environ, HOME=str(home),
                       FACO_WATCH_CONFIG_DIR=str(cfgdir), FACO_TEST_MARKER=str(marker),
                       PYTHONDONTWRITEBYTECODE='1')
            p = subprocess.Popen([sys.executable, '-u', str(ROOT / 'scripts' / 'boot_agent.py')],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env)
            try:
                time.sleep(.12)
                self.assertIsNone(p.poll(), 'Agent should still be waiting for installation')
                self.assertFalse(marker.exists())
                (install / 'faco_watch').mkdir(parents=True)
                (install / 'faco_watch' / 'cli.py').write_text('# worker fixture\n')
                (install / 'bin').mkdir()
                (install / 'bin' / 'faco-resource-watch').write_text(
                    'import json, os, time\n'
                    'from pathlib import Path\n'
                    'Path(os.environ["FACO_TEST_MARKER"]).write_text('
                    'json.dumps({"pid":os.getpid()}))\n'
                    'while True:time.sleep(.15)\n')
                for _ in range(100):
                    if marker.exists():
                        break
                    time.sleep(.06)
                self.assertTrue(marker.exists(), 'Worker should launch once files appear')
                self.assertEqual(json.loads(marker.read_text())['pid'], p.pid,
                                 'exec must preserve same PID for systemd supervision')
                self.assertIsNone(p.poll(), 'Worker should remain alive in background')
            finally:
                p.terminate()
                try:p.communicate(timeout=3)
                except subprocess.TimeoutExpired:p.kill();p.communicate(timeout=3)


if __name__=='__main__':
    unittest.main()

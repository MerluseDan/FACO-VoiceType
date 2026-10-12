"""Installer/upgrade/uninstall tests isolated from actual host user directories."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from install import is_removable_location, validate_custom, resolve_paths, base_dir


def stub(path, code):
    path.write_text('#!/usr/bin/env bash\nset -e\n' + code + '\n')
    path.chmod(0o755)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / 'Linux home with spaces'
        self.home.mkdir()
        self.app = self.home / '.local/share/faco-resource-watch/app'
        self.data = self.home / '.local/share/faco-resource-watch/data'
        self.logs = self.home / '.local/state/faco-resource-watch/logs'
        self.cfg = self.home / '.config/faco-resource-watch'
        self.bin = self.root / 'fake binaries'
        self.bin.mkdir()
        stub(self.bin / 'systemctl', 'echo "$*" >> "$HOME/systemctl-calls"')
        stub(self.bin / 'loginctl', 'echo "$*" >> "$HOME/loginctl-calls"\n'
             'if [[ " $* " == *" show-user "* ]]; then\n'
             '  if [[ -f "$HOME/linger-flag" ]]; then echo yes; else echo no; fi\n'
             'elif [[ " $* " == *" enable-linger "* ]]; then\n'
             '  touch "$HOME/linger-flag"\nfi')
        stub(self.bin / 'gnome-extensions', 'echo "$*" >> "$HOME/extension-calls"')
        self.env = dict(os.environ, HOME=str(self.home), USER='faco_test',
                        PATH=str(self.bin)+':'+os.environ.get('PATH', ''),
                        FACO_INSTALL_NONINTERACTIVE='1',
                        XDG_RUNTIME_DIR=str(self.root/'runtime'),
                        PYTHONDONTWRITEBYTECODE='1')
        for envvar in list(self.env):
            if envvar.startswith('FACO_WATCH_') or envvar in ('FACO_RESOURCE_ROOT',
                  'XDG_CONFIG_HOME','XDG_DATA_HOME','XDG_STATE_HOME'):
                self.env.pop(envvar, None)
        (self.root/'runtime').mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, expected=0, **settings):
        env={**self.env, **settings}
        run=subprocess.run(['bash', str(ROOT/'install.sh')], cwd=ROOT, env=env,
                           text=True, capture_output=True, timeout=40)
        self.assertEqual(run.returncode, expected, run.stdout+'\n'+run.stderr)
        return run.stdout + run.stderr

    def test_default_fresh_install_is_xdg_and_does_not_probe_custom_drive(self):
        out=self.install()
        self.assertIn('Custom mounts: None', out)
        self.assertTrue((self.app/'web/index.html').is_file())
        self.assertTrue((self.app/'LICENSE').is_file())
        self.assertTrue((self.data/'history.sqlite3').is_file())
        self.assertTrue((self.logs/'collector.log').is_file() or self.logs.is_dir())
        self.assertTrue((self.home/'.local/share/applications/faco-resource-watch.desktop').exists())
        self.assertTrue((self.home/'.local/share/gnome-shell/extensions/faco-resource-watch@faco.local/extension.js').is_file())
        self.assertEqual((self.home/'.local/bin/faco-resource-watch').resolve(),
                         self.app/'bin/faco-resource-watch')
        unit = (self.home/'.config/systemd/user/faco-resource-watch.service')
        self.assertTrue(unit.is_file())
        self.assertIn('Restart=always', unit.read_text())
        self.assertIn('ExecStart=/usr/bin/python3', unit.read_text())
        self.assertIn('"FACO_WATCH_CONFIG_DIR=', unit.read_text())
        self.assertEqual(json.loads((self.cfg/'startup.json').read_text())['install_dir'], str(self.app))
        self.assertEqual(json.loads((self.cfg/'startup.json').read_text())['require_mounts'], [])
        self.assertEqual(json.loads((self.cfg/'paths.json').read_text())['data_dir'], str(self.data))
        self.assertTrue((self.home/'linger-flag').exists())
        if shutil.which('systemd-analyze'):
            result=subprocess.run(['systemd-analyze', 'verify', str(unit)],
                                  text=True, capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_reinstall_preserves_existing_data_exactly(self):
        self.install()
        db=self.data/'history.sqlite3'
        before=db.read_bytes()
        (self.data/'some-other-file').write_text('private user notes')
        self.install()
        self.assertEqual(db.read_bytes(), before)
        self.assertEqual((self.data/'some-other-file').read_text(), 'private user notes')
        self.assertIn('enable --now', (self.home/'systemctl-calls').read_text())

    def test_public_install_remains_default_even_with_unrelated_existing_drive(self):
        strange_drive=self.root/'mounted private drive'
        strange_drive.mkdir()
        self.install(FACO_RESOURCE_ROOT=str(strange_drive))
        self.assertTrue(self.app.is_dir())
        self.assertFalse((strange_drive/'Apps').exists())

    def test_explicit_custom_path_only_when_requested(self):
        parent=self.root/'user selected drive'/'Apps'
        parent.mkdir(parents=True)
        desired=parent/'Resource Watch'
        custom_data=parent/'Resource Watch Database'
        out=self.install(FACO_WATCH_INSTALL_DIR=str(desired),
                         FACO_WATCH_DATA_DIR=str(custom_data))
        self.assertTrue((desired/'web/app.js').is_file())
        self.assertTrue((custom_data/'history.sqlite3').is_file())
        self.assertFalse(self.app.exists())
        self.assertEqual(json.loads((self.cfg/'startup.json').read_text())['install_dir'], str(desired))
        self.assertEqual(json.loads((self.cfg/'paths.json').read_text())['data_dir'], str(custom_data))
        self.assertIn('Custom mounts: None',out)  # /tmp doesn't require a USB mount

    def test_missing_custom_location_cancels_without_side_effects(self):
        missing = self.root/'not created'/'Apps'/'FACO_Resource_Watch'
        out = self.install(expected=1, FACO_WATCH_INSTALL_DIR=str(missing))
        self.assertIn('Use OS Default Location', out)
        self.assertIn('Cancel Installation', out)
        self.assertFalse(self.app.exists())
        self.assertFalse(self.cfg.exists())
        self.assertFalse((self.home/'systemctl-calls').exists())

    def test_explicit_os_default_recovery_from_missing_custom_path(self):
        missing=self.root/'missing volume'/'FACO_Resource_Watch'
        result=self.install(FACO_WATCH_INSTALL_DIR=str(missing),
                            FACO_WATCH_MISSING_CUSTOM='default')
        self.assertIn('Explicit choice: Use OS Default Location', result)
        self.assertTrue(self.app.exists())
        self.assertEqual(json.loads((self.cfg/'startup.json').read_text())['install_dir'], str(self.app))

    def test_old_database_migration_replays_committed_wal(self):
        legacy=self.root/'previous FACO disk'/'Apps'/'FACO_Resource_Watch'
        old_data=legacy/'data'
        old_data.mkdir(parents=True)
        self.cfg.mkdir(parents=True)
        (self.cfg/'startup.json').write_text(json.dumps({'install_dir':str(legacy), 'require_mount':None}))
        (self.cfg/'paths.json').write_text(json.dumps({'data_dir':str(old_data)}))
        legacy_log=legacy/'_logs'
        legacy_log.mkdir()
        (legacy_log/'collector.log').write_text('legacy log content')
        conn=sqlite3.connect(old_data/'history.sqlite3')
        try:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('CREATE TABLE important_history (sample TEXT)')
            conn.execute("INSERT INTO important_history VALUES ('please keep me')")
            conn.commit()
            self.assertTrue((old_data/'history.sqlite3-wal').exists())
            result=self.install()
            self.assertIn('Preserved existing history with verified SQLite backup',result)
            with sqlite3.connect(self.data/'history.sqlite3') as new_db:
                self.assertEqual(new_db.execute('SELECT sample FROM important_history').fetchone()[0],
                                 'please keep me')
            self.assertTrue((old_data/'history.sqlite3').exists())
            self.assertEqual((self.logs/'legacy-collector.log').read_text(), 'legacy log content')
        finally:
            conn.close()

    def test_legacy_missing_drive_requires_explicit_choice(self):
        self.cfg.mkdir(parents=True)
        missing = self.root/'unmounted old drive'/'Apps'/'FACO_Resource_Watch'
        (self.cfg/'startup.json').write_text(json.dumps({'install_dir':str(missing)}))
        (self.cfg/'paths.json').write_text(json.dumps({'data_dir':str(missing/'data')}))
        out=self.install(expected=1)
        self.assertIn('Previously configured install location',out)
        self.assertFalse(self.app.exists())
        out=self.install(FACO_WATCH_MISSING_CUSTOM='default')
        self.assertIn('Explicit choice: Use OS Default Location',out)
        self.assertTrue(self.app.exists())

    def test_uninstall_preserves_history_and_never_disables_linger(self):
        self.install()
        hist=self.data/'history.sqlite3'
        uninstall=subprocess.run(['bash',str(self.app/'uninstall.sh')], env=self.env,
                                 text=True,capture_output=True,timeout=10)
        self.assertEqual(uninstall.returncode,0,uninstall.stderr)
        self.assertFalse(self.app.exists())
        self.assertFalse((self.cfg/'startup.json').exists())
        self.assertFalse((self.home/'.local/bin/faco-resource-watch').exists())
        self.assertTrue(hist.exists())
        self.assertTrue((self.home/'linger-flag').exists())
        self.assertNotIn('disable-linger', (self.home/'loginctl-calls').read_text())

    def test_uninstall_purge_cleans_only_owned_db_not_other_files(self):
        self.install()
        (self.data/'unrelated.txt').write_text('keep')
        p=subprocess.run(['bash',str(self.app/'uninstall.sh'),'--purge-data'],
                         env=self.env,text=True,capture_output=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertFalse((self.data/'history.sqlite3').exists())
        self.assertEqual((self.data/'unrelated.txt').read_text(),'keep')

    def test_xdg_overrides_are_respected(self):
        xdg_data=self.root/'data home';xdg_cfg=self.root/'config home';xdg_state=self.root/'state home'
        self.install(XDG_DATA_HOME=str(xdg_data), XDG_CONFIG_HOME=str(xdg_cfg),
                     XDG_STATE_HOME=str(xdg_state))
        self.assertTrue((xdg_data/'faco-resource-watch/app/web/index.html').exists())
        self.assertTrue((xdg_data/'faco-resource-watch/data/history.sqlite3').exists())
        self.assertTrue((xdg_cfg/'faco-resource-watch/boot_agent.py').exists())
        self.assertTrue((xdg_state/'faco-resource-watch/logs').exists())
        self.assertFalse(self.app.exists())

    def test_existing_unrelated_launcher_prevents_install_before_service_changes(self):
        launcher=self.home/'.local/bin/faco-resource-watch'
        launcher.parent.mkdir(parents=True)
        launcher.write_text('someone else owns this executable')
        out=self.install(expected=1)
        self.assertIn('Existing launcher is not ours',out)
        self.assertEqual(launcher.read_text(),'someone else owns this executable')
        self.assertFalse(self.app.exists())
        self.assertFalse((self.home/'systemctl-calls').exists())

    def test_removable_paths_are_detected_without_hardcoded_developer_drive(self):
        for example in ('/media/someone/usb_drive/myapp', '/run/media/abc/backup/resource',
                        '/mnt/external/faco'):
            self.assertTrue(is_removable_location(Path(example)), example)
        mount, error=validate_custom(Path('/media/nonexistent_unique_user/nonexistent_device/App'),
                                     'Test custom storage')
        self.assertIsNone(mount)
        self.assertIsNotNone(error)
        self.assertTrue('mounted drive' in error or 'not a writable directory' in error, error)


if __name__=='__main__':
    unittest.main()

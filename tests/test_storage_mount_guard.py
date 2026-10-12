"""Prevent unintended system-disk writes when selected removable storage disappears."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from faco_watch import storage


class StorageMountTests(unittest.TestCase):
    def test_no_local_fallback_after_custom_drive_unmounts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cfg = root/'config'
            cfg.mkdir()
            (cfg/'startup.json').write_text(json.dumps({'install_dir':str(root/'installed'),
                                     'require_mounts':['/mnt/another-drive']}))
            history = root/'fresh-data-folder'/'history.sqlite3'
            with mock.patch.object(storage, 'CONFIG', cfg), \
                 mock.patch('pathlib.Path.is_mount', return_value=False):
                with self.assertRaisesRegex(OSError, 'Configured storage mount unavailable'):
                    storage.connect(path=history)
            self.assertFalse(history.exists())
            self.assertFalse(history.parent.exists())

    def test_absent_removable_path_does_not_create_fake_mount(self):
        path = Path('/run/media/faco-example/missing_drive/data/history.sqlite3')
        with mock.patch('pathlib.Path.is_mount', return_value=False):
            with self.assertRaisesRegex(OSError, 'External storage not mounted'):
                storage.connect(path=path)
        self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()

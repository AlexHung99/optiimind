from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import opti_update as update
from opti_install import install_app


def archive(version='1.1.0', extra=None):
    files = {name: b'# test\n' for name in ('opti_app.py', 'opti_update.py', 'opti_bootstrap.py', 'opti_version.py')}
    files.update({'opti-requirements.txt': b'Pillow\n', 'Start-OptiiChat.cmd': b'@echo off\n'})
    files.update(extra or {})
    files['package-files.json'] = json.dumps({'version': version, 'files': {name: update.digest(data) for name, data in files.items()}}).encode()
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w') as output:
        for name, data in files.items():
            output.writestr(name, data)
    return result.getvalue(), files


class UpdateTests(unittest.TestCase):
    def test_installer_upgrade_does_not_replace_unmanaged_new_filename(self):
        with tempfile.TemporaryDirectory() as temp:
            source, installed = Path(temp)/'source', Path(temp)/'installed'
            source.mkdir()
            installed.mkdir()
            self.old_install(installed)
            (installed/'opti_pdf.py').write_bytes(b'# user file')
            _, files = archive('1.1.0', {'opti_pdf.py': b'# release file'})
            for name, data in files.items():
                (source/name).write_bytes(data)
            with self.assertRaisesRegex(RuntimeError, 'unmanaged'):
                install_app(source, installed)
            self.assertEqual((installed/'opti_pdf.py').read_bytes(), b'# user file')

    def test_manual_check_replaces_an_older_pending_update(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'pending.json').write_text(json.dumps({'version': '1.0.1'}))
            self.stage(root)
            self.assertEqual(json.loads((root/'pending.json').read_text())['version'], '1.1.0')

    def test_fresh_install_and_reinstall_protect_customization(self):
        with tempfile.TemporaryDirectory() as temp:
            source, installed = Path(temp)/'source', Path(temp)/'installed'
            source.mkdir()
            self.old_install(source)
            install_app(source, installed)
            self.assertEqual((installed/'opti_app.py').read_bytes(), b'# old\n')
            (installed/'opti_app.py').write_text('# customized')
            with self.assertRaisesRegex(RuntimeError, 'modifications'):
                install_app(source, installed)
            self.assertEqual((installed/'opti_app.py').read_text(), '# customized')

    def test_install_rejects_corrupt_source(self):
        with tempfile.TemporaryDirectory() as temp:
            source, installed = Path(temp)/'source', Path(temp)/'installed'
            source.mkdir()
            self.old_install(source)
            (source/'opti_app.py').write_text('# corrupted')
            with self.assertRaisesRegex(RuntimeError, 'checksum'):
                install_app(source, installed)
            self.assertFalse(installed.exists())

    def stage(self, directory):
        data, files = archive()
        manifest = {'version': '1.1.0', 'sha256': update.digest(data), 'url': 'https://raw.githubusercontent.com'+update.DOWNLOAD_PREFIX+'OptiiChat-1.1.0.zip'}
        with patch.object(update, 'fetch_bytes', side_effect=[json.dumps(manifest).encode(), data]):
            message = update.check_for_update('1.0.0', directory, True)
        self.assertIn('已下載', message)
        return files

    def old_install(self, root):
        _, files = archive('1.0.0', {'opti_app.py': b'# old\n'})
        for name, data in files.items():
            (root/name).write_bytes(data)
        return files

    def test_stage_apply_preserves_unmanaged_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root, stage = Path(temp)/'app', Path(temp)/'updates'
            root.mkdir()
            old = self.old_install(root)
            (root/'my-notes.txt').write_text('keep')
            files = self.stage(stage)
            self.assertEqual((root/'opti_app.py').read_bytes(), old['opti_app.py'])
            self.assertTrue(update.apply_pending(root, stage))
            self.assertEqual((root/'opti_app.py').read_bytes(), files['opti_app.py'])
            self.assertEqual((root/'my-notes.txt').read_text(), 'keep')
            self.assertFalse((stage/'pending.json').exists())
            self.assertEqual(len(list(stage.glob('backup-*.zip'))), 1)

    def test_local_changes_stop_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root, stage = Path(temp)/'app', Path(temp)/'updates'
            root.mkdir()
            self.old_install(root)
            self.stage(stage)
            (root/'opti_app.py').write_text('# custom')
            with self.assertRaisesRegex(RuntimeError, '本機程式修改'):
                update.apply_pending(root, stage)
            self.assertEqual((root/'opti_app.py').read_text(), '# custom')

    def test_failed_write_rolls_back(self):
        with tempfile.TemporaryDirectory() as temp:
            root, stage = Path(temp)/'app', Path(temp)/'updates'
            root.mkdir()
            old = self.old_install(root)
            self.stage(stage)
            real_write = update.atomic_write
            failed = False
            def write(path, data):
                nonlocal failed
                if Path(path).name == 'opti_bootstrap.py' and not failed:
                    failed = True
                    raise OSError('locked')
                real_write(path, data)
            with patch.object(update, 'atomic_write', side_effect=write):
                with self.assertRaises(OSError):
                    update.apply_pending(root, stage)
            for name, data in old.items():
                self.assertEqual((root/name).read_bytes(), data)

    def test_bad_hash_paths_and_versions_rejected(self):
        data, _ = archive()
        with self.assertRaises(ValueError):
            update.unpack_verified(data, '0'*64, '1.1.0')
        for path in ('../outside.py', 'opti_assets/../../notes.txt', 'C:/evil.py', 'settings.json', 'opti_assets/CON.png'):
            with self.assertRaises(ValueError):
                update.safe_name(path)
        with self.assertRaises(ValueError):
            update.version_tuple('1.2.3;evil')
        self.assertGreater(update.version_tuple('1.10.0'), update.version_tuple('1.9.0'))

    def test_newer_source_must_be_expected_repository(self):
        manifest = {'version': '2.0.0', 'url': 'https://example.com/evil.zip', 'sha256': '0'*64}
        with tempfile.TemporaryDirectory() as temp, patch.object(update, 'fetch_bytes', return_value=json.dumps(manifest).encode()) as fetch:
            with self.assertRaises(ValueError):
                update.check_for_update('1.0.0', temp, True)
            self.assertEqual(fetch.call_count, 1)

    def test_same_or_older_version_does_not_download(self):
        for version in ('1.0.0', '0.9.0'):
            with tempfile.TemporaryDirectory() as temp, patch.object(update, 'fetch_bytes', return_value=json.dumps({'version': version}).encode()) as fetch:
                self.assertIn('最新', update.check_for_update('1.0.0', temp, True))
                self.assertEqual(fetch.call_count, 1)


if __name__ == '__main__':
    unittest.main()

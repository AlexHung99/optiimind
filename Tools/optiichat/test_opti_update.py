from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import zipfile
import opti_update as update
import opti_bootstrap as bootstrap
import opti_install
import opti_setup
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
    def test_first_launch_starts_missing_dependency_install_automatically(self):
        original_tk = opti_setup.tk.Tk
        def guarded_root():
            root = original_tk()
            timeout = root.after(3000, root.destroy)
            root.bind('<Destroy>', lambda event: root.after_cancel(timeout)
                      if event.widget is root else None, add=True)
            return root
        with patch.object(opti_setup.tk, 'Tk', side_effect=guarded_root), \
             patch.object(opti_setup, 'install_ollama') as ollama, \
             patch.object(opti_setup, 'install_compat') as compat:
            self.assertTrue(opti_setup.run_setup())
        ollama.assert_called_once()
        compat.assert_called_once()

    def test_missing_ollama_uses_verified_official_installer(self):
        response = io.BytesIO(b'installer data')
        response.url = opti_install.OLLAMA_SETUP_URL
        with patch.object(opti_install, 'ollama_installed', side_effect=[False, True]), \
             patch.object(opti_install, 'urlopen', return_value=response) as download, \
             patch.object(opti_install, 'verify_ollama_signature') as verify, \
             patch.object(opti_install.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            opti_install.install_ollama(progress=lambda _: None)
        self.assertEqual(download.call_args.args[0].full_url, opti_install.OLLAMA_SETUP_URL)
        verify.assert_called_once()
        self.assertEqual(run.call_args.args[0][1:], ['/VERYSILENT', '/NORESTART', '/SUPPRESSMSGBOXES'])

    def test_invalid_ollama_signature_stops_before_execution(self):
        response = io.BytesIO(b'installer data')
        response.url = opti_install.OLLAMA_SETUP_URL
        with patch.object(opti_install, 'ollama_installed', return_value=False), \
             patch.object(opti_install, 'urlopen', return_value=response), \
             patch.object(opti_install, 'verify_ollama_signature', side_effect=RuntimeError('bad signature')), \
             patch.object(opti_install.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'bad signature'):
                opti_install.install_ollama(progress=lambda _: None)
        run.assert_not_called()

    def test_launcher_waits_for_tray_exit_when_update_is_pending(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory/'pending.json').write_text('{}')
            with patch.object(bootstrap, 'app_running', side_effect=[True, True, False]) as running, \
                 patch.object(bootstrap.time, 'sleep') as sleep:
                self.assertTrue(bootstrap.ready_to_update(directory, checks=3))
            self.assertEqual(running.call_count, 3)
            self.assertEqual(sleep.call_count, 2)
            with patch.object(bootstrap, 'app_running', return_value=True), \
                 patch.object(bootstrap.time, 'sleep') as sleep:
                self.assertFalse(bootstrap.ready_to_update(directory, checks=2))
            self.assertEqual(sleep.call_count, 2)

    def test_launcher_does_not_wait_without_pending_update(self):
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(bootstrap, 'app_running', return_value=True), \
             patch.object(bootstrap.time, 'sleep') as sleep:
            self.assertFalse(bootstrap.ready_to_update(temp))
            sleep.assert_not_called()

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
        manifest = {'version': '1.1.0', 'sha256': update.digest(data), 'url': update.UPDATE_ORIGIN+'/OptiiChat-1.1.0.zip'}
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

    def test_startup_always_checks_and_applies_pending_update(self):
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(bootstrap, 'UPDATE_DIR', Path(temp)), \
             patch.object(bootstrap, 'ready_to_update', return_value=True), \
             patch.object(bootstrap, 'check_for_update', return_value='新版已下載') as check, \
             patch.object(bootstrap, 'apply_pending', return_value=True) as apply:
            self.assertTrue(bootstrap.apply_waiting_update(Path(temp)))
            check.assert_called_once_with(force=True)
            apply.assert_called_once()

    def test_offline_startup_uses_old_version_and_retries_later(self):
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(bootstrap, 'UPDATE_DIR', Path(temp)), \
             patch.object(bootstrap, 'ready_to_update', return_value=True), \
             patch.object(bootstrap, 'check_for_update', side_effect=OSError('offline')) as check, \
             patch.object(bootstrap, 'apply_pending', return_value=False) as apply:
            self.assertTrue(bootstrap.apply_waiting_update(Path(temp)))
            self.assertIn('offline', (Path(temp)/'last-error.txt').read_text(encoding='utf-8'))
            check.assert_called_once_with(force=True)
            apply.assert_called_once()

    def test_staged_archive_is_not_downloaded_twice(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            data, _ = archive()
            manifest = {'version': '1.1.0', 'sha256': update.digest(data),
                        'url': update.UPDATE_ORIGIN+'/OptiiChat-1.1.0.zip'}
            (directory/'OptiiChat-1.1.0.zip').write_bytes(data)
            (directory/'pending.json').write_text(json.dumps({
                'version': '1.1.0', 'sha256': manifest['sha256'], 'archive': 'OptiiChat-1.1.0.zip'}))
            with patch.object(update, 'fetch_bytes', return_value=json.dumps(manifest).encode()) as fetch:
                self.assertIn('已下載', update.check_for_update('1.0.0', directory, True))
            self.assertEqual(fetch.call_count, 1)

    def test_previous_check_does_not_hide_new_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory/'last-check').touch()
            data, _ = archive()
            manifest = {'version': '1.1.0', 'sha256': update.digest(data),
                        'url': update.UPDATE_ORIGIN+'/OptiiChat-1.1.0.zip'}
            with patch.object(update, 'fetch_bytes', side_effect=[json.dumps(manifest).encode(), data]) as fetch:
                self.assertIn('已下載', update.check_for_update('1.0.0', directory))
            self.assertEqual(fetch.call_count, 2)

    def test_same_or_older_version_does_not_download(self):
        for version in ('1.0.0', '0.9.0'):
            with tempfile.TemporaryDirectory() as temp, patch.object(update, 'fetch_bytes', return_value=json.dumps({'version': version}).encode()) as fetch:
                self.assertIn('最新', update.check_for_update('1.0.0', temp, True))
                self.assertEqual(fetch.call_count, 1)


if __name__ == '__main__':
    unittest.main()

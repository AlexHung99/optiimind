"""Versioned, hash-checked R2 updates; applied by the launcher before Tk starts."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import zipfile

from opti_version import VERSION

UPDATE_ORIGIN = 'https://optiichat-update.optiimind.com'
UPDATE_URL = UPDATE_ORIGIN+'/update.json'
DOWNLOAD_PREFIX = '/'
UPDATE_DIR = Path(os.environ.get('LOCALAPPDATA', Path.home()))/'OptiiChat'/'updates'
MAX_ZIP = 25 * 1024 * 1024
MAX_EXPANDED = 60 * 1024 * 1024


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+\.\d+\.\d+', value):
        raise ValueError('更新版本格式無效。')
    return tuple(map(int, value.split('.')))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.optii-', delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def fetch_bytes(url, limit):
    with urlopen(Request(url, headers={'User-Agent': 'OptiiChat/'+VERSION,
                                       'Cache-Control': 'no-cache, no-store', 'Pragma': 'no-cache'}), timeout=25) as response:
        requested, actual = urlparse(url), urlparse(response.url)
        if actual.scheme != 'https' or actual.netloc != requested.netloc or actual.path != requested.path:
            raise ValueError('更新下載跳轉至非預期來源。')
        result = response.read(limit + 1)
    if len(result) > limit:
        raise ValueError('更新檔案超過大小限制。')
    return result


def safe_name(name):
    path = PurePosixPath(name)
    if not name or '\\' in name or ':' in name or path.is_absolute() or any(p in ('', '.', '..') for p in name.split('/')):
        raise ValueError('更新包包含不安全的檔案路徑。')
    # Updates own only app files and logo assets, never settings, models, or sibling projects.
    if len(path.parts) == 1:
        allowed = name in ('Start-OptiiChat.cmd', 'Start-Llama32-UI.cmd', 'Start-Llama32-Vision.cmd',
                           'Install-OptiiChat.cmd', 'README.md', 'OptiiChat-使用說明.md', 'opti-requirements.txt',
                           'package-files.json', 'llama_vision_ui.py', 'start_llama32_vision.py',
                           'test_llama_vision_ui.py', 'test_opti_chat.py', 'test_opti_update.py',
                           'test_opti_agent.py') or re.fullmatch(r'opti_[a-z_]+\.py', name)
    else:
        allowed = len(path.parts) == 2 and path.parts[0] == 'opti_assets' and (path.name == 'README.md' or re.fullmatch(r'logo-[a-z]+\.png', path.name))
    if not allowed:
        raise ValueError('更新包包含非程式檔案：'+name)
    return path


def unpack_verified(data, expected_hash, version):
    if not re.fullmatch(r'[a-f0-9]{64}', expected_hash) or digest(data) != expected_hash:
        raise ValueError('更新 SHA-256 驗證失敗。')
    files = {}
    folded = set()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist()) > 120 or sum(entry.file_size for entry in archive.infolist()) > MAX_EXPANDED:
            raise ValueError('更新包解壓大小異常。')
        for entry in archive.infolist():
            safe_name(entry.filename)
            if entry.filename.casefold() in folded or entry.is_dir() or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('更新包含重複路徑或連結。')
            folded.add(entry.filename.casefold())
            files[entry.filename] = archive.read(entry)
    package = json.loads(files.get('package-files.json', b'{}'))
    if package.get('version') != version or set(package.get('files', {})) != set(files)-{'package-files.json'}:
        raise ValueError('更新包版本或檔案清單不符。')
    for name, checksum in package['files'].items():
        if digest(files[name]) != checksum:
            raise ValueError('更新包內檔案驗證失敗：'+name)
    for required in ('opti_app.py', 'opti_update.py', 'opti_version.py', 'opti_bootstrap.py', 'opti-requirements.txt', 'Start-OptiiChat.cmd'):
        if required not in files:
            raise ValueError('更新包缺少必要檔案：'+required)
    return files


def check_for_update(current=VERSION, directory=None, force=False):
    directory = Path(directory or UPDATE_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    pending = directory/'pending.json'
    item = None
    if pending.exists():
        item = json.loads(pending.read_text(encoding='utf-8'))
    checked = directory/'last-check'
    # Do not skip the manifest because a previous check or pending ZIP exists.
    manifest = json.loads(fetch_bytes(UPDATE_URL+'?t='+str(time.time_ns()), 65536))
    version = manifest.get('version')
    if version_tuple(version) <= version_tuple(current):
        checked.touch()
        return '目前已是最新版本 '+current+'。'
    url = manifest.get('url', '')
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.netloc != urlparse(UPDATE_ORIGIN).netloc or parsed.path != DOWNLOAD_PREFIX+'OptiiChat-'+version+'.zip' or parsed.query or parsed.fragment:
        raise ValueError('更新來源不是指定的 OptiChat R2 網域。')
    if (item and item.get('version') == version and item.get('sha256') == manifest.get('sha256')
            and item.get('archive') == 'OptiiChat-'+version+'.zip'):
        archive = directory/item['archive']
        if archive.is_file() and archive.stat().st_size <= MAX_ZIP and digest(archive.read_bytes()) == item['sha256']:
            checked.touch()
            return '新版 '+version+' 已下載；從系統匣「結束程式」後重新開啟即可套用。'
    data = fetch_bytes(url, MAX_ZIP)
    unpack_verified(data, manifest.get('sha256', ''), version)
    filename = 'OptiiChat-'+version+'.zip'
    atomic_write(directory/filename, data)
    atomic_write(pending, json.dumps({'version': version, 'sha256': manifest['sha256'], 'archive': filename}).encode())
    checked.touch()
    return '新版 '+version+' 已下載；從系統匣「結束程式」後重新開啟即可套用。'


def target_path(root, name):
    safe_name(name)
    target = root.joinpath(*PurePosixPath(name).parts)
    if target.is_symlink() or target.parent.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('更新目標超出程式目錄。')
    return target


def apply_pending(root, directory=None, installer=None):
    root, directory = Path(root), Path(directory or UPDATE_DIR)
    pending = directory/'pending.json'
    if not pending.exists():
        return False
    manifest = json.loads(pending.read_text(encoding='utf-8'))
    version = manifest['version']
    version_tuple(version)
    if manifest.get('archive') != 'OptiiChat-'+version+'.zip':
        raise ValueError('更新暫存檔名無效。')
    archive = directory/manifest['archive']
    if archive.stat().st_size > MAX_ZIP:
        raise ValueError('更新檔案超過大小限制。')
    files = unpack_verified(archive.read_bytes(), manifest['sha256'], version)
    baseline_path = root/'package-files.json'
    if not baseline_path.exists():
        raise RuntimeError('此程式目錄沒有發行清單，請先使用官網 ZIP 安裝。')
    baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
    if version_tuple(version) <= version_tuple(baseline['version']):
        pending.unlink()
        return False
    for name, checksum in baseline['files'].items():
        target = target_path(root, name)
        if not target.is_file() or digest(target.read_bytes()) != checksum:
            raise RuntimeError('偵測到本機程式修改，更新已暫停：'+name)
    for name in files:
        target = target_path(root, name)
        if target.exists() and name not in baseline['files'] and name != 'package-files.json':
            raise RuntimeError('更新檔案與本機未管理的檔案同名：'+name)
    old_requirements = (root/'opti-requirements.txt').read_bytes()
    if old_requirements != files['opti-requirements.txt']:
        if installer is None:
            raise RuntimeError('新版需要安裝相依套件，請透過啟動檔更新。')
        installer(files['opti-requirements.txt'])
    originals = {name: target_path(root, name).read_bytes() if target_path(root, name).exists() else None for name in files}
    backup = directory/('backup-'+baseline['version']+'-'+str(time.time_ns())+'.zip')
    with zipfile.ZipFile(backup, 'w', zipfile.ZIP_DEFLATED) as out:
        for name, data in originals.items():
            if data is not None:
                out.writestr(name, data)
    written = []
    try:
        for name, data in files.items():
            atomic_write(target_path(root, name), data)
            written.append(name)
    except Exception:
        for name in reversed(written):
            if originals[name] is None:
                target_path(root, name).unlink(missing_ok=True)
            else:
                atomic_write(target_path(root, name), originals[name])
        raise
    pending.unlink()
    archive.unlink(missing_ok=True)
    return True


def app_running():
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenMutexW(0x00100000, False, 'Local\\OptiiChat.Desktop.Instance')
    if handle:
        kernel.CloseHandle(handle)
        return True
    return False

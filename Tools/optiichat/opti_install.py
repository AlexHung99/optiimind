"""Install the UI environment and the official CPU/Vulkan compatibility runtime."""
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen
import venv
import zipfile
from opti_update import atomic_write, digest, target_path, version_tuple

ROOT = Path(__file__).resolve().parent
LOCAL = Path(os.environ.get('LOCALAPPDATA', Path.home()))
COMPAT = LOCAL/'Programs'/'Ollama-Llama32-Compat'
OLLAMA_SETUP_URL = 'https://ollama.com/download/OllamaSetup.exe'


def ollama_installed():
    return (LOCAL/'Programs'/'Ollama'/'ollama.exe').is_file() or bool(shutil.which('ollama'))


def verify_ollama_signature(installer):
    script = ("$sig = Get-AuthenticodeSignature -LiteralPath $env:OPTII_OLLAMA_INSTALLER; "
              "if ($sig.Status -ne 'Valid' -or "
              "$sig.SignerCertificate.Subject -notmatch '(^|, )O=Ollama Inc\\.(,|$)') { exit 1 }")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
        env={**os.environ, 'OPTII_OLLAMA_INSTALLER': str(installer)},
        capture_output=True, timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('Ollama 官方安裝檔簽章驗證失敗，已停止安裝。')


def install_ollama(progress=print, cancelled=None):
    if ollama_installed():
        return
    progress('正在下載 Ollama 官方安裝檔…')
    request = Request(OLLAMA_SETUP_URL, headers={'User-Agent': 'OptiChat-Installer'})
    with tempfile.TemporaryDirectory(prefix='OptiChat-Ollama-') as temp:
        installer = Path(temp)/'OllamaSetup.exe'
        with urlopen(request, timeout=60) as response, installer.open('wb') as output:
            if not response.url.startswith('https://'):
                raise RuntimeError('Ollama 安裝檔下載來源不是 HTTPS。')
            total = 0
            while chunk := response.read(1024*1024):
                if cancelled and cancelled.is_set():
                    raise RuntimeError('Ollama 下載已取消。')
                total += len(chunk)
                if total > 4 * 1024**3:
                    raise RuntimeError('Ollama 安裝檔超過大小限制。')
                output.write(chunk)
                progress(f'下載 Ollama：{total/1024**2:.0f} MB')
        if cancelled and cancelled.is_set():
            raise RuntimeError('Ollama 安裝已取消。')
        progress('正在驗證 Ollama 官方程式碼簽章…')
        verify_ollama_signature(installer)
        progress('正在安裝 Ollama…')
        result = subprocess.run([str(installer), '/VERYSILENT', '/NORESTART', '/SUPPRESSMSGBOXES'],
            timeout=1800, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise RuntimeError(f'Ollama 安裝失敗（代碼 {result.returncode}）。')
        for _ in range(120):
            if ollama_installed():
                return
            time.sleep(1)
        raise RuntimeError('Ollama 安裝程序已結束，但找不到 ollama.exe。')


def install_app(source=ROOT, destination=None):
    source = Path(source)
    destination = Path(destination or LOCAL/'OptiiChat'/'app')
    manifest_data = (source/'package-files.json').read_bytes()
    package = json.loads(manifest_data)
    version_tuple(package['version'])
    files = {}
    for name, checksum in package['files'].items():
        data = target_path(source, name).read_bytes()
        if digest(data) != checksum:
            raise RuntimeError('Installation file checksum mismatch: '+name)
        files[name] = data
    existing = destination/'package-files.json'
    owned = set()
    if existing.exists():
        baseline = json.loads(existing.read_text(encoding='utf-8'))
        owned = set(baseline['files'])
        if version_tuple(baseline['version']) > version_tuple(package['version']):
            print('A newer app version is already installed; keeping it.')
            return
        for name, checksum in baseline['files'].items():
            path = target_path(destination, name)
            if not path.is_file() or digest(path.read_bytes()) != checksum:
                raise RuntimeError('Local app modifications detected: '+name)
    for name, data in files.items():
        path = target_path(destination, name)
        if name not in owned and path.exists() and path.read_bytes() != data:
            raise RuntimeError('An unmanaged app file already exists: '+name)
    for name, data in files.items():
        atomic_write(target_path(destination, name), data)
    atomic_write(existing, manifest_data)


def install_compat(progress=print, cancelled=None):
    if (COMPAT/'ollama.exe').exists():
        version = subprocess.run([str(COMPAT/'ollama.exe'), '--version'], capture_output=True, text=True, timeout=15)
        if '0.24.0' in version.stdout+version.stderr:
            return
        raise RuntimeError('A different compatibility runtime is installed; refusing to overwrite it.')
    progress('正在下載官方 Vision 相容服務（約 2.1 GB）…')
    req = Request('https://api.github.com/repos/ollama/ollama/releases/tags/v0.24.0', headers={'User-Agent': 'OptiiChat-Installer'})
    with urlopen(req, timeout=30) as response:
        release = json.load(response)
    asset = next(item for item in release['assets'] if item['name'] == 'ollama-windows-amd64.zip')
    expected = asset.get('digest', '')
    if not expected.startswith('sha256:'):
        raise RuntimeError('Official release has no SHA-256 digest; cannot verify runtime download.')
    url = asset['browser_download_url']
    if not url.startswith('https://github.com/ollama/ollama/releases/download/v0.24.0/'):
        raise RuntimeError('Unexpected runtime download source.')
    with tempfile.TemporaryDirectory(prefix='OptiiChat-runtime-') as temp:
        archive_path = Path(temp)/'ollama.zip'
        checksum = hashlib.sha256()
        with urlopen(url, timeout=60) as response, archive_path.open('wb') as output:
            total = 0
            while chunk := response.read(1024*1024):
                if cancelled and cancelled.is_set():
                    raise RuntimeError('下載已取消。')
                output.write(chunk)
                checksum.update(chunk)
                total += len(chunk)
                progress(f'下載相容服務：{total/1024**2:.0f} / {asset["size"]/1024**2:.0f} MB')
        progress('正在驗證及解壓縮相容服務…')
        if checksum.hexdigest() != expected.split(':', 1)[1]:
            raise RuntimeError('Ollama download checksum mismatch.')
        staged = Path(temp)/'runtime'
        with zipfile.ZipFile(archive_path) as archive:
            for entry in archive.infolist():
                if cancelled and cancelled.is_set():
                    raise RuntimeError('安裝已取消。')
                name = PurePosixPath(entry.filename)
                if name.is_absolute() or '..' in name.parts or '\\' in entry.filename or ':' in entry.filename:
                    raise RuntimeError('Unsafe runtime archive path.')
                # CUDA/ROCm payloads are not needed by the CPU/Vulkan compatibility service.
                if entry.is_dir() or any('cuda' in part.lower() or 'rocm' in part.lower() for part in name.parts):
                    continue
                target = staged.joinpath(*name.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output)
        if not (staged/'ollama.exe').is_file():
            raise RuntimeError('Runtime archive is incomplete.')
        COMPAT.parent.mkdir(parents=True, exist_ok=True)
        COMPAT.mkdir(exist_ok=True)
        shutil.copytree(staged, COMPAT, dirs_exist_ok=True)


def create_desktop_shortcut():
    """Use Windows' actual desktop folder, including OneDrive redirection."""
    app = LOCAL/'OptiiChat'/'app'
    pythonw = LOCAL/'OptiiChat'/'python'/'pythonw.exe'
    if not pythonw.is_file():
        pythonw = LOCAL/'OptiiChat'/'runtime'/'Scripts'/'pythonw.exe'
    if not pythonw.is_file():
        pythonw = COMPAT/'ui-venv'/'Scripts'/'pythonw.exe'
    if not pythonw.is_file() or not (app/'opti_bootstrap.py').is_file():
        raise RuntimeError('Install OptiiChat before creating its desktop shortcut.')
    icon = LOCAL/'OptiiChat'/'app-icon.ico'
    # Generate a square, padded Windows icon from the existing official logo.
    icon_code = '''from PIL import Image
import sys
with Image.open(sys.argv[1]) as source:
    mark = source.convert('RGBA')
mark.thumbnail((224, 224), Image.Resampling.LANCZOS)
canvas = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
canvas.alpha_composite(mark, ((256-mark.width)//2, (256-mark.height)//2))
canvas.save(sys.argv[2], format='ICO', sizes=[(n,n) for n in (16,24,32,48,64,128,256)])
'''
    subprocess.run([str(pythonw.with_name('python.exe')), '-c', icon_code,
                    str(app/'opti_assets'/'logo-teal.png'), str(icon)],
                   check=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    script = '''$ErrorActionPreference = 'Stop'
$desktop = [Environment]::GetFolderPath('DesktopDirectory')
if (-not $desktop) { throw 'Windows desktop folder is unavailable.' }
$shortcutPath = Join-Path $desktop 'OptiChat.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $env:OPTII_SHORTCUT_PYTHON
$shortcut.Arguments = '"' + (Join-Path $env:OPTII_SHORTCUT_APP 'opti_bootstrap.py') + '"'
$shortcut.WorkingDirectory = $env:OPTII_SHORTCUT_APP
$shortcut.IconLocation = $env:OPTII_SHORTCUT_ICON + ',0'
$shortcut.Description = 'OptiChat - Local AI workspace'
$shortcut.Save()
$legacyPath = Join-Path $desktop 'OptiiChat.lnk'
if (Test-Path -LiteralPath $legacyPath) {
    $legacy = $shell.CreateShortcut($legacyPath)
    if ($legacy.Arguments -eq $shortcut.Arguments -and $legacy.WorkingDirectory -eq $shortcut.WorkingDirectory) {
        Remove-Item -LiteralPath $legacyPath
    }
}
'''
    environment = dict(os.environ, OPTII_SHORTCUT_APP=str(app),
                       OPTII_SHORTCUT_PYTHON=str(pythonw), OPTII_SHORTCUT_ICON=str(icon))
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                   env=environment, check=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    print('OptiChat desktop shortcut created.')


def main():
    if sys.platform != 'win32' or sys.version_info < (3, 11):
        raise RuntimeError('Install Python 3.11 or newer for Windows from https://www.python.org/downloads/windows/')
    install_ollama()
    runtime = LOCAL/'OptiiChat'/'runtime'
    if not (runtime/'Scripts'/'python.exe').exists():
        venv.EnvBuilder(with_pip=True).create(runtime)
    subprocess.run([str(runtime/'Scripts'/'python.exe'), '-m', 'pip', 'install', '-r', str(ROOT/'opti-requirements.txt')], check=True)
    install_compat()
    install_app()
    create_desktop_shortcut()
    print('Installation complete. The app downloads llama3.2-vision if no models are installed.')


if __name__ == '__main__':
    try:
        if '--install-bundled' in sys.argv:
            import argparse
            parser = argparse.ArgumentParser()
            parser.add_argument('--install-bundled', action='store_true')
            parser.add_argument('--destination')
            parser.add_argument('--no-shortcut', action='store_true')
            args = parser.parse_args()
            install_app(destination=args.destination)
            if not args.no_shortcut:
                create_desktop_shortcut()
        else:
            main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)

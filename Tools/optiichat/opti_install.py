"""Install the UI environment and the official CPU/Vulkan compatibility runtime."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen
import venv
import zipfile
from opti_update import atomic_write, digest, target_path, version_tuple

ROOT = Path(__file__).resolve().parent
LOCAL = Path(os.environ.get('LOCALAPPDATA', Path.home()))
COMPAT = LOCAL/'Programs'/'Ollama-Llama32-Compat'


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
    if existing.exists():
        baseline = json.loads(existing.read_text(encoding='utf-8'))
        if version_tuple(baseline['version']) > version_tuple(package['version']):
            print('A newer app version is already installed; keeping it.')
            return
        for name, checksum in baseline['files'].items():
            path = target_path(destination, name)
            if not path.is_file() or digest(path.read_bytes()) != checksum:
                raise RuntimeError('Local app modifications detected: '+name)
    for name, data in files.items():
        path = target_path(destination, name)
        if not existing.exists() and path.exists() and path.read_bytes() != data:
            raise RuntimeError('An unmanaged app file already exists: '+name)
    for name, data in files.items():
        atomic_write(target_path(destination, name), data)
    atomic_write(existing, manifest_data)


def install_compat():
    if (COMPAT/'ollama.exe').exists():
        version = subprocess.run([str(COMPAT/'ollama.exe'), '--version'], capture_output=True, text=True, timeout=15)
        if '0.24.0' in version.stdout+version.stderr:
            return
        raise RuntimeError('A different compatibility runtime is installed; refusing to overwrite it.')
    print('Downloading official Ollama 0.24.0 compatibility runtime (large download)…', flush=True)
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
                output.write(chunk)
                checksum.update(chunk)
                total += len(chunk)
                print(f'\r{total/1024**2:.0f} / {asset["size"]/1024**2:.0f} MB', end='', flush=True)
        print()
        if checksum.hexdigest() != expected.split(':', 1)[1]:
            raise RuntimeError('Ollama download checksum mismatch.')
        staged = Path(temp)/'runtime'
        with zipfile.ZipFile(archive_path) as archive:
            for entry in archive.infolist():
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


def main():
    if sys.platform != 'win32' or sys.version_info < (3, 11):
        raise RuntimeError('Install Python 3.11 or newer for Windows from https://www.python.org/downloads/windows/')
    ollama = LOCAL/'Programs'/'Ollama'/'ollama.exe'
    if not ollama.exists() and not shutil.which('ollama'):
        raise RuntimeError('Install Ollama for Windows first: https://ollama.com/download/windows')
    runtime = LOCAL/'OptiiChat'/'runtime'
    if not (runtime/'Scripts'/'python.exe').exists():
        venv.EnvBuilder(with_pip=True).create(runtime)
    subprocess.run([str(runtime/'Scripts'/'python.exe'), '-m', 'pip', 'install', '-r', str(ROOT/'opti-requirements.txt')], check=True)
    install_compat()
    install_app()
    print('Installation complete. The app downloads llama3.2-vision if no models are installed.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)

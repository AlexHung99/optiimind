"""Build with CPython x64 and NSIS: python build.py --makensis PATH [--prepare-only]."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT.parents[1]/'.installer-build'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--makensis', type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--test', action='store_true')
    args = parser.parse_args()
    runtime = BUILD/'python'
    if not (runtime/'bundle-ready.json').exists():
        if runtime.exists():
            raise RuntimeError('Incomplete runtime exists; inspect it before rebuilding.')
        base = Path(sys.base_prefix)
        runtime.mkdir(parents=True)
        # Copy only the Python distribution, never a user's site-packages or venv.
        for name in ('python.exe', 'pythonw.exe', 'python3.dll', 'LICENSE.txt'):
            shutil.copy2(base/name, runtime/name)
        for pattern in ('python3*.dll', 'vcruntime*.dll'):
            for file in base.glob(pattern):
                shutil.copy2(file, runtime/file.name)
        for name in ('DLLs', 'Lib', 'tcl'):
            shutil.copytree(base/name, runtime/name,
                            ignore=shutil.ignore_patterns('site-packages', '__pycache__', 'test', 'tests', 'idlelib', 'ensurepip'))
        site = runtime/'Lib'/'site-packages'
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--only-binary=:all:', '--no-compile',
                        '--target', str(site), '-r', str(ROOT/'opti-requirements.txt'), 'pip==25.3'], check=True)
        subprocess.run([str(runtime/'python.exe'), '-I', '-c',
                        'import tkinter, PIL, psutil, pystray, pynvml, pyttsx3, win32api, comtypes, pip; r=tkinter.Tk(); r.withdraw(); r.destroy(); print("Bundled runtime OK")'], check=True)
        (runtime/'bundle-ready.json').write_text(json.dumps({'python':sys.version, 'requirements':(ROOT/'opti-requirements.txt').read_text()}), encoding='utf-8')
    info = json.loads((runtime/'bundle-ready.json').read_text())
    if info['requirements'] != (ROOT/'opti-requirements.txt').read_text():
        raise RuntimeError('Requirements changed; build a fresh runtime.')
    if args.prepare_only:
        return
    if not args.makensis:
        parser.error('--makensis is required')
    package = json.loads((ROOT/'package-files.json').read_text(encoding='utf-8'))
    stage = BUILD/('app-'+package['version'])
    stage.mkdir(exist_ok=True)
    for name, expected in package['files'].items():
        data = (ROOT/name).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError('Run opti_release.py before building: '+name)
        dest = stage/name
        dest.parent.mkdir(exist_ok=True, parents=True)
        dest.write_bytes(data)
    shutil.copy2(ROOT/'package-files.json', stage/'package-files.json')
    from PIL import Image
    with Image.open(ROOT/'opti_assets'/'logo-teal.png') as source:
        logo = source.convert('RGBA')
    logo.thumbnail((224,224), Image.Resampling.LANCZOS)
    icon = Image.new('RGBA', (256,256))
    icon.alpha_composite(logo, ((256-logo.width)//2,(256-logo.height)//2))
    icon.save(BUILD/'app.ico', sizes=[(n,n) for n in (16,24,32,48,64,128,256)])
    output = BUILD/'OptiChat-Test.exe' if args.test else ROOT/'downloads'/f'OptiChat-Setup-{package["version"]}.exe'
    command = [str(args.makensis.resolve()), '/INPUTCHARSET', 'UTF8', '/V2',
               '/DVERSION='+package['version'], '/DPYTHON_SOURCE='+str(runtime),
               '/DAPP_SOURCE='+str(stage), '/DAPP_ICON='+str(BUILD/'app.ico'), '/DOUTPUT='+str(output)]
    if args.test:
        command.append('/DTEST_ROOT='+str(BUILD/'install-smoke'))
    subprocess.run(command+[str(ROOT/'installer'/'setup.nsi')], check=True)
    data = output.read_bytes()
    print(json.dumps({'file':str(output), 'size':len(data), 'sha256':hashlib.sha256(data).hexdigest()}))
    if not args.test:
        (ROOT/'installer.json').write_text(json.dumps({'version':package['version'],
            'url':'downloads/'+output.name, 'bytes':len(data), 'sha256':hashlib.sha256(data).hexdigest(), 'signed':False}, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()

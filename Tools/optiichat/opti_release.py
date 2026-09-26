"""Maintainer utility: build a versioned ZIP and its R2 update manifest."""
import argparse
import ast
import json
from pathlib import Path
import zipfile
from opti_update import UPDATE_ORIGIN, digest, safe_name, unpack_verified
from opti_version import VERSION


def build(root=None, bridge_github=False):
    root = Path(root or Path(__file__).resolve().parent)
    names = ['Start-OptiiChat.cmd', 'Start-Llama32-UI.cmd', 'Start-Llama32-Vision.cmd',
             'Install-OptiiChat.cmd', 'README.md', 'OptiiChat-使用說明.md', 'opti-requirements.txt',
             'llama_vision_ui.py', 'start_llama32_vision.py', 'test_llama_vision_ui.py',
             'test_opti_chat.py', 'test_opti_update.py', 'test_opti_agent.py']
    names += [path.name for path in root.glob('opti_*.py')]
    names += [path.relative_to(root).as_posix() for path in (root/'opti_assets').iterdir() if path.is_file()]
    files = {}
    for name in sorted(set(names)):
        safe_name(name)
        data = (root/name).read_bytes()
        if name.endswith('.py'):
            ast.parse(data)
        files[name] = data
    package = {'version': VERSION, 'files': {name: digest(data) for name, data in files.items()}}
    files['package-files.json'] = json.dumps(package, indent=2, ensure_ascii=False).encode('utf-8')
    (root/'package-files.json').write_bytes(files['package-files.json'])
    downloads = root/'downloads'
    downloads.mkdir(exist_ok=True)
    archive = downloads/('OptiiChat-'+VERSION+'.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            output.writestr(info, data)
    checksum = digest(archive.read_bytes())
    unpack_verified(archive.read_bytes(), checksum, VERSION)
    manifest = {'version': VERSION, 'sha256': checksum,
                'url': f'{UPDATE_ORIGIN}/{archive.name}'}
    (root/'r2-update.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    if bridge_github:
        legacy = dict(manifest, url=f'https://raw.githubusercontent.com/AlexHung99/optiimind/main/Tools/optiichat/downloads/{archive.name}')
        (root/'update.json').write_text(json.dumps(legacy, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'archive': str(archive), 'bytes': archive.stat().st_size, **manifest}, ensure_ascii=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bridge-github', action='store_true', help='Publish a one-time GitHub manifest for pre-R2 clients')
    build(bridge_github=parser.parse_args().bridge_github)

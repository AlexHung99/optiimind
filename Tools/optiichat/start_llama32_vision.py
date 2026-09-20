"""Start the official Ollama 0.24 compatibility service and open the vision model."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(os.environ['LOCALAPPDATA']) / 'Programs' / 'Ollama-Llama32-Compat'
EXE = ROOT / 'ollama.exe'
HOST = '127.0.0.1:11435'
MODEL = 'llama3.2-vision:latest'

def version():
    try:
        with urllib.request.urlopen(f'http://{HOST}/api/version', timeout=2) as response:
            return json.load(response)['version']
    except (urllib.error.URLError, TimeoutError):
        return None

def ensure_service():
    env = os.environ.copy()
    env.update(OLLAMA_HOST=HOST, OLLAMA_MODELS=str(Path.home()/'.ollama'/'models'),
               OLLAMA_VULKAN='0', OLLAMA_CONTEXT_LENGTH='2048')
    current = version()
    if current is None:
        with (ROOT/'server.stdout.log').open('ab') as out, (ROOT/'server.stderr.log').open('ab') as err:
            process = subprocess.Popen([str(EXE), 'serve'], env=env, cwd=ROOT,
                                       stdout=out, stderr=err, creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(30):
            current = version()
            if current is not None:
                break
            if process.poll() is not None:
                raise RuntimeError('Ollama did not start; see server.stderr.log in '+str(ROOT))
            time.sleep(1)
    if current != '0.24.0':
        raise RuntimeError(f'Expected Ollama 0.24.0 on {HOST}, got {current!r}')
    return env

def main():
    env = ensure_service()
    current = '0.24.0'
    print(f'Ollama {current} | {HOST} | {MODEL}', flush=True)
    print('CPU compatibility mode. Image processing and replies may take a while.', flush=True)
    if '--check' not in sys.argv:
        print('Enter a message, or include the full path to an image. Type /bye to exit.', flush=True)
        return subprocess.call([str(EXE), 'run', MODEL], env=env)
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)

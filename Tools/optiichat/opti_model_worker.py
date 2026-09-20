"""Download the fixed default from Ollama's official registry, reporting NDJSON."""
import json
import sys
from urllib.request import Request, urlopen


def main():
    request = Request('http://127.0.0.1:11434/api/pull',
                      data=json.dumps({'model': 'llama3.2-vision', 'stream': True}).encode(),
                      headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=120) as response:
        for line in response:
            if line.strip():
                event = json.loads(line)
                print(json.dumps(event, ensure_ascii=True), flush=True)
                if event.get('error'):
                    return 1
                if event.get('status') == 'success':
                    return 0
    raise RuntimeError('Ollama 下載連線提前結束，請重試。')


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=True), flush=True)
        sys.exit(1)

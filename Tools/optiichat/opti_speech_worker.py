"""Isolated SAPI worker: allows stopping generation without touching the Tk thread."""
import json
from pathlib import Path
import sys
import pyttsx3

def main():
    if sys.argv[1] != '--voices':
        job = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
        if job['provider'] == 'breeze':
            from opti_core import generate_breeze
            generate_breeze(job, job['text'], Path(job['output']))
            return
    engine = pyttsx3.init('sapi5')
    if sys.argv[1] == '--voices':
        print(json.dumps([{'id': v.id, 'name': v.name} for v in engine.getProperty('voices')], ensure_ascii=True))
        return
    job = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    if job['voice_id']:
        engine.setProperty('voice', job['voice_id'])
    engine.setProperty('rate', job['rate'])
    engine.setProperty('volume', job['volume'])
    engine.save_to_file(job['text'], job['output'])
    engine.runAndWait()
    engine.stop()

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)

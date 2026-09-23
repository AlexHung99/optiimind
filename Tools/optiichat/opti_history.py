"""Local conversation snapshots. Files are data, never executable code."""
from datetime import datetime
import json
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4

from opti_core import DATA

HISTORY_DIR = DATA/'history'
ID_PATTERN = re.compile(r'[0-9a-f]{32}\Z')


def new_record():
    now = datetime.now().astimezone().isoformat(timespec='seconds')
    return {'id':uuid4().hex, 'title':datetime.now().strftime('%Y-%m-%d %H:%M'),
            'created':now, 'updated':now, 'transcript':'', 'messages':[], 'draft':''}


def path_for(identifier, directory=HISTORY_DIR):
    if not ID_PATTERN.fullmatch(identifier):
        raise ValueError('對話編號無效。')
    return Path(directory)/(identifier+'.json')


def save_record(record, directory=HISTORY_DIR):
    target = path_for(record['id'], directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    record['updated'] = datetime.now().astimezone().isoformat(timespec='seconds')
    # Images are never stored as base64; prior image turns have already been
    # intentionally excluded by the chat model's short context window.
    clean = dict(record)
    clean['messages'] = [{'role':m['role'], 'content':m['content']}
                         for m in record['messages'] if m.get('role') in ('user', 'assistant')]
    payload = json.dumps(clean, ensure_ascii=False, indent=2)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=target.parent,
                                     prefix='.conversation-', suffix='.tmp', delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(payload)
    try:
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def list_records(directory=HISTORY_DIR):
    result = []
    for path in Path(directory).glob('*.json'):
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            if path.stem == record['id'] and ID_PATTERN.fullmatch(record['id']):
                result.append(record)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(result, key=lambda item:item.get('created', ''), reverse=True)


def load_record(identifier, directory=HISTORY_DIR):
    return json.loads(path_for(identifier, directory).read_text(encoding='utf-8'))

"""Local conversation snapshots. Files are data, never executable code."""
from datetime import datetime
import json
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4

from PIL import Image

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


def preview_path(identifier, index, directory=None):
    if not isinstance(identifier, str) or not ID_PATTERN.fullmatch(identifier) or not isinstance(index, int) or index < 0:
        raise ValueError('對話預覽編號無效。')
    return Path(directory or HISTORY_DIR)/(identifier+'-'+str(index)+'.jpg')


def save_preview(identifier, index, image, directory=None):
    """Persist only a small, metadata-free image for a sent chat attachment."""
    target = preview_path(identifier, index, directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    thumbnail = image.copy().convert('RGB')
    thumbnail.thumbnail((220, 150), Image.Resampling.LANCZOS)
    clean = Image.new('RGB', thumbnail.size, 'white')
    clean.paste(thumbnail)
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.preview-', suffix='.jpg',
                                     delete=False) as stream:
        temporary = Path(stream.name)
    try:
        clean.save(temporary, format='JPEG', quality=78, optimize=True)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def save_record(record, directory=HISTORY_DIR):
    target = path_for(record['id'], directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    record['updated'] = datetime.now().astimezone().isoformat(timespec='seconds')
    # Full images are never stored in JSON; only small visual previews are
    # persisted separately for conversation history.
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

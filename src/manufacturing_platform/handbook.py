"""Fixed release document reader. No filesystem access until an authorized read."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import stat
from typing import Literal

Document = Literal['handbook', 'workflow']
_DOCUMENTS = {
    'handbook': ('大制造数字化系统手册', 'docs/manufacturing-system-handbook.md'),
    'workflow': ('制造业务流程总览', 'docs/workflows/manufacturing-process-overview.md'),
}


def _regular_file(root, relative):
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or not stat.S_ISREG(target.stat().st_mode):
        raise ValueError('Invalid release document')
    return target


def read_handbook(assets_dir, document, release):
    title, source_path = _DOCUMENTS[document]
    root = Path(assets_dir).resolve().parent.parent
    metadata = json.loads(_regular_file(root, 'handbook-metadata.json').read_bytes())
    entry = metadata['files'][source_path]
    if not isinstance(entry, dict) or set(entry) != {'updated_at', 'sha256'}:
        raise ValueError('Invalid document metadata')
    digest, updated_at = entry['sha256'], entry['updated_at']
    if not isinstance(digest, str) or re.fullmatch('[0-9a-f]{64}', digest) is None:
        raise ValueError('Invalid document digest')
    if not isinstance(updated_at, str):
        raise ValueError('Invalid document timestamp')
    timestamp = datetime.fromisoformat(updated_at)
    if timestamp.tzinfo is None or timestamp.utcoffset() != timezone.utc.utcoffset(timestamp):
        raise ValueError('Invalid document timestamp')
    content = _regular_file(root, source_path).read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError('Invalid document digest')
    return {'title': title, 'markdown': content.decode('utf-8'), 'updated_at': updated_at,
            'sha256': digest, 'source_path': source_path, 'release': release}

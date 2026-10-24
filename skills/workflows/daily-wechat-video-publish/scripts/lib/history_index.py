"""跨轮次视频去重索引。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_INDEX = Path('/Users/ddt/work/臻肆/视频/processed_index.json')


def load_index(path: Path = DEFAULT_INDEX) -> dict[str, Any]:
    if not path.exists():
        return {'version': 1, 'entries': []}
    return json.loads(path.read_text(encoding='utf-8'))


def save_index(data: dict[str, Any], path: Path = DEFAULT_INDEX) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def composite_key(candidate: dict[str, Any]) -> str:
    src = candidate.get('source', candidate)
    if candidate.get('sha256'):
        return f"sha256:{candidate['sha256']}"
    cover = src.get('coverText') or src.get('coverPreview', '')
    parts = [
        src.get('group', ''),
        src.get('sender', ''),
        src.get('messageTime', ''),
        cover,
        str(src.get('duration', '')),
    ]
    return 'composite:' + '|'.join(parts)


def is_processed(candidate: dict[str, Any], index: dict[str, Any] | None = None) -> bool:
    idx = index or load_index()
    key = composite_key(candidate)
    for entry in idx.get('entries', []):
        if entry.get('key') == key and entry.get('state') in ('submitted', 'verified', 'downloaded'):
            return True
    return False


def record_entry(
    candidate: dict[str, Any],
    *,
    run_id: str,
    state: str,
    path: Path = DEFAULT_INDEX,
) -> None:
    idx = load_index(path)
    key = composite_key(candidate)
    entries = [e for e in idx.get('entries', []) if e.get('key') != key]
    entries.append({
        'key': key,
        'runId': run_id,
        'state': state,
        'group': candidate.get('source', candidate).get('group'),
        'sender': candidate.get('source', candidate).get('sender'),
        'messageTime': candidate.get('source', candidate).get('messageTime'),
        'localFile': candidate.get('localFile'),
        'sha256': candidate.get('sha256'),
        'updatedAt': datetime.now(timezone.utc).isoformat(),
    })
    idx['entries'] = entries
    save_index(idx, path)

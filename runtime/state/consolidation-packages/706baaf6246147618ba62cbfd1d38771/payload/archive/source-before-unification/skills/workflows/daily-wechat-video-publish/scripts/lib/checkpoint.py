"""群+发送人维度的扫描游标：首次 yesterday 19:00，后续从上次记录时间继续。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage_paths import video_root
CHECKPOINT_FILE = video_root() / 'scan_checkpoint.json'


def key(group: str, sender: str) -> str:
    return f'{group}|{sender}'


def load(path: Path = CHECKPOINT_FILE) -> dict[str, Any]:
    if not path.exists():
        return {'version': 1, 'entries': {}}
    return json.loads(path.read_text(encoding='utf-8'))


def save(data: dict[str, Any], path: Path = CHECKPOINT_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def get_last_cutoff(group: str, sender: str, path: Path = CHECKPOINT_FILE) -> str | None:
    data = load(path)
    entry = data.get('entries', {}).get(key(group, sender))
    return entry.get('lastMessageTime') if entry else None


def update_checkpoint(
    group: str,
    sender: str,
    last_message_time: str,
    run_id: str,
    path: Path = CHECKPOINT_FILE,
) -> None:
    data = load(path)
    entries = data.setdefault('entries', {})
    entries[key(group, sender)] = {
        'group': group,
        'sender': sender,
        'lastMessageTime': last_message_time,
        'lastRunId': run_id,
        'updatedAt': datetime.now(timezone.utc).isoformat(),
    }
    save(data, path)

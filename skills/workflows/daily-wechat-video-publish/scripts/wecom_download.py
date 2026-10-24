"""企业微信指定企业、指定群 MP4 的扫描与精确缓存落盘。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.wecom_media import (
    MediaError,
    copy_verified,
    make_preview,
    media_duration_seconds,
    select_exact_cache,
    select_native_batch,
)


def _read_rows(run: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (run / 'candidates.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]


def _write_rows(run: Path, rows: list[dict[str, Any]]) -> None:
    (run / 'candidates.jsonl').write_text(
        ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8'
    )


def _timeline(run: Path, node: str, **values: Any) -> None:
    with (run / 'timeline.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({
            'node': node,
            'at': datetime.now(timezone.utc).isoformat(),
            'runtimeModelDecision': False,
            **values,
        }, ensure_ascii=False) + '\n')


def _meta(run: Path) -> dict[str, Any]:
    value = json.loads((run / 'run.json').read_text(encoding='utf-8'))
    if value.get('source', {}).get('type') != 'wecom_desktop':
        raise RuntimeError('批次来源不是 wecom_desktop')
    return value


def scan_group(run: Path) -> dict[str, Any]:
    from lib.wecom_desktop import discover, discover_native_videos

    meta = _meta(run)
    artifacts = run / 'artifacts' / 'wecom-preflight'
    existing = _read_rows(run)
    known = {(row.get('source') or {}).get('filename') for row in existing}
    added = []
    if meta.get('sender'):
        native, screenshot = discover_native_videos(
            meta['group'], meta['source']['enterpriseMarker'], meta['sender'], artifacts
        )
        cutoff = datetime.fromisoformat(meta['cutoff'])
        native = [item for item in native if datetime.fromisoformat(item.message_time) > cutoff]
        for item in native:
            identity = f"native:{item.message_time}:{item.duration_seconds}:{item.row_sequence}"
            if identity in known:
                continue
            row = {
                'id': str(uuid.uuid4()),
                'source': {
                    'type': 'wecom_desktop',
                    'kind': 'native_video',
                    'enterprise': meta['enterprise'],
                    'group': meta['group'],
                    'sender': item.sender,
                    'messageTime': item.message_time,
                    'durationSeconds': item.duration_seconds,
                    'rowSequence': item.row_sequence,
                    'filename': identity,
                },
                'state': 'download_pending',
            }
            existing.append(row)
            added.append(row)
        count = len(native)
    else:
        attachments, screenshot = discover(meta['group'], meta['source']['enterpriseMarker'], artifacts)
        extensions = tuple(meta['source'].get('extensions') or ['.mp4'])
        attachments = [item for item in attachments if item.filename.lower().endswith(extensions)]
        for item in attachments:
            if item.filename in known:
                continue
            row = {
                'id': str(uuid.uuid4()),
                'source': {
                    'type': 'wecom_desktop',
                    'kind': 'file_attachment',
                    'enterprise': meta['enterprise'],
                    'group': meta['group'],
                    'sender': '',
                    'messageTime': meta.get('cutoff') or '',
                    'filename': item.filename,
                    'uiSize': item.ui_size,
                },
                'state': 'download_pending',
            }
            existing.append(row)
            added.append(row)
        count = len(attachments)
    expected = int(meta['source']['expectedCount'])
    if expected == 0:
        expected = count
        meta['source']['expectedCount'] = expected
        (run / 'run.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    _write_rows(run, existing)
    _timeline(run, 'wecom_scan_done', count=count, added=len(added), expected=expected)
    return {
        'ok': count > 0 and count == expected,
        'count': count,
        'expected': expected,
        'candidates': added,
        'evidence': str(screenshot),
        'error': '' if count > 0 and count == expected else 'candidate_count_mismatch',
    }


def download_pending(run: Path) -> dict[str, Any]:
    meta = _meta(run)
    rows = _read_rows(run)
    errors = []
    downloaded = 0
    native_rows = [row for row in rows if row.get('state') == 'download_pending' and row.get('source', {}).get('kind') == 'native_video']
    if native_rows:
        try:
            earliest = min(datetime.fromisoformat(row['source']['messageTime']) for row in native_rows)
            files = select_native_batch(
                [int(row['source']['durationSeconds']) for row in native_rows], after=earliest
            )
            remaining = list(files)
            for index, row in enumerate(native_rows, 1):
                wanted = int(row['source']['durationSeconds'])
                choices = [path for path in remaining if int(media_duration_seconds(path) + 0.5) == wanted]
                if not choices:
                    raise MediaError(f'没有可绑定的 {wanted} 秒缓存视频')
                cache = choices[0]
                remaining.remove(cache)
                stamp = datetime.fromisoformat(row['source']['messageTime']).strftime('%Y%m%d-%H%M')
                destination = run / 'videos' / f'{stamp}-{index:02d}-{wanted}s{cache.suffix.lower()}'
                receipt = copy_verified(cache, destination)
                preview = make_preview(destination, run / 'artifacts' / 'previews')
                row.update(receipt)
                row['cacheSource'] = str(cache)
                row['coverThumb'] = str(preview) if preview else ''
                row['state'] = 'human_review_pending'
                downloaded += 1
        except (MediaError, OSError) as exc:
            for row in native_rows:
                if row.get('state') == 'download_pending':
                    row['state'] = 'download_unknown'
                    row['note'] = str(exc)
            errors.append({'kind': 'native_batch', 'error': str(exc)})

    for row in rows:
        if row.get('state') != 'download_pending':
            continue
        source = row['source']
        try:
            cache = select_exact_cache(source['filename'], source['uiSize'])
            destination = run / 'videos' / source['filename']
            receipt = copy_verified(cache, destination)
            preview = make_preview(destination, run / 'artifacts' / 'previews')
            row.update(receipt)
            row['cacheSource'] = str(cache)
            row['coverThumb'] = str(preview) if preview else ''
            row['state'] = 'human_review_pending'
            downloaded += 1
        except (MediaError, OSError) as exc:
            row['state'] = 'download_unknown'
            row['note'] = str(exc)
            errors.append({'filename': source.get('filename'), 'error': str(exc)})
    _write_rows(run, rows)
    expected = int(meta['source']['expectedCount'])
    completed_states = {'human_review_pending', 'prepared', 'publish_pending', 'submitted', 'verified'}
    successful = [
        row for row in rows
        if row.get('state') in completed_states
        and row.get('sha256')
        and Path(row.get('localFile') or '').is_file()
    ]
    complete = len(successful) == expected and not errors
    if not complete:
        meta['state'] = 'download_incomplete'
    elif meta.get('state') not in ('captions_prepared', 'publish_pending', 'submitted', 'verified'):
        meta['state'] = 'human_review_pending'
    (run / 'run.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    cursor = ''
    if complete:
        from lib.wecom_config import state_dir

        cursor = max(row['source'].get('messageTime') or '' for row in successful)
        checkpoint_dir = state_dir(run.parents[3], meta['enterprise'], meta['group'])
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        (checkpoint_dir / 'checkpoint.json').write_text(json.dumps({
            'enterprise': meta['enterprise'],
            'group': meta['group'],
            'lastMessageTime': cursor,
            'lastRunId': meta['runId'],
            'updatedAt': datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    _timeline(run, 'wecom_download_done', downloaded=downloaded, expected=expected, ok=complete, cursor=cursor)
    return {
        'ok': complete,
        'downloaded': len(successful),
        'downloadedThisCall': downloaded,
        'expected': expected,
        'errors': errors,
        'cursor': cursor,
        'runDir': str(run),
    }

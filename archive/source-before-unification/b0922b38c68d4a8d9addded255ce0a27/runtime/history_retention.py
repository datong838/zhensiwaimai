"""Archive dated historical logs; never traverse business state for cleanup."""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tarfile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
STATUSES = {'SUCCESS', 'FAILED', 'SKIPPED', 'SKIPPED_BUSY'}
CATEGORIES = {'SUCCESS', 'RECOVERABLE', 'UNKNOWN', 'FATAL', 'LOGIN_REQUIRED'}


def dated(value):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def identity(file):
    with file.open('rb') as handle:
        sha = hashlib.file_digest(handle, 'sha256').hexdigest()
    return {'size': file.stat().st_size, 'sha256': sha}


def snapshot(directory):
    if directory.is_symlink():
        raise ValueError('symlink-not-archivable')
    result = {}
    for file in sorted(directory.rglob('*')):
        if file.is_symlink() or not (file.is_dir() or file.is_file()):
            raise ValueError('non-regular-history-entry')
        if file.is_file():
            result[file.relative_to(directory).as_posix()] = identity(file)
    return result


def verify_archive(file, day, expected):
    actual = {}
    with tarfile.open(file, 'r:gz') as archive:
        for member in archive:
            if not member.isfile() or not member.name.startswith(day + '/'):
                raise ValueError('invalid-archive-entry')
            name = member.name[len(day) + 1:]
            if name in actual or '..' in Path(name).parts or Path(name).is_absolute():
                raise ValueError('invalid-archive-path')
            with archive.extractfile(member) as handle:
                actual[name] = {'size': member.size,
                                'sha256': hashlib.file_digest(handle, 'sha256').hexdigest()}
    if actual != expected:
        raise ValueError('archive-content-mismatch')


def idle(root):
    steps = root / 'runtime/state/live_steps'
    if steps.exists() and any(steps.iterdir()):
        raise ValueError('active-workflow-maintenance-deferred')


def archive_day(root, directory, *, today=None):
    idle(root)
    if directory.parent != root / 'runtime/run_history' or dated(directory.name) is None:
        raise ValueError('outside-history-scope')
    today = today or dt.datetime.now(ZoneInfo('Asia/Shanghai')).date()
    if dated(directory.name) >= today - dt.timedelta(days=2):
        raise ValueError('within-three-day-window')
    if directory.parent.is_symlink():
        raise ValueError('history-root-symlink')
    before = snapshot(directory)
    target = root / '.local/history-archive'
    if (root / '.local').is_symlink() or target.is_symlink():
        raise ValueError('archive-destination-symlink')
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    archive = target / (directory.name + '.tar.gz')
    temp = target / (directory.name + '.tar.gz.tmp')
    index = target / (directory.name + '.index.json')
    if any(file.is_symlink() for file in (archive, temp, index)):
        raise ValueError('archive-file-symlink')
    if archive.exists():
        verify_archive(archive, directory.name, before)
    else:
        # Exclusive creation leaves an interrupted attempt visible, never overwritten.
        with temp.open('xb') as output:
            os.chmod(temp, 0o600)
            with tarfile.open(fileobj=output, mode='w:gz') as bundle:
                for name in before:
                    bundle.add(directory / name, arcname=directory.name + '/' + name,
                               recursive=False)
        verify_archive(temp, directory.name, before)
        os.link(temp, archive)
        temp.unlink()
    idle(root)
    if snapshot(directory) != before:
        raise ValueError('history-changed-during-archive')
    value = {'schemaVersion': 1, 'day': directory.name, 'files': before,
             'archive': identity(archive)}
    if index.exists() and json.loads(index.read_text()) != value:
        raise ValueError('archive-index-conflict')
    index.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    index.chmod(0o600)
    # Quarantine by atomic rename before final removal. A changed source stays recoverable.
    staging = target / (directory.name + '.source')
    if staging.exists():
        raise ValueError('archive-staging-exists')
    directory.rename(staging)
    if snapshot(staging) != before:
        raise ValueError('quarantined-history-changed')
    shutil.rmtree(staging)
    return {'day': directory.name, 'files': len(before),
            'originalBytes': sum(row['size'] for row in before.values()),
            'archiveBytes': archive.stat().st_size}


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        return dt.datetime.fromisoformat(value).isoformat()
    except ValueError:
        return None


def reference_rows(root, today):
    manifest = json.loads((root / 'runtime/skills_manifest.json').read_text())
    known = {item['name'] for item in manifest['skills']}
    rows = []
    for offset in range(2, -1, -1):
        day = (today - dt.timedelta(days=offset)).isoformat()
        directory = root / 'runtime/run_history' / day
        if directory.is_symlink():
            continue
        for file in sorted(directory.glob('*--record.json')):
            if file.is_symlink():
                continue
            record = json.loads(file.read_text())
            if record.get('skill') not in known or record.get('status') not in STATUSES:
                continue
            row = {'day': day, 'workflow': record['skill'], 'status': record['status']}
            if record.get('category') in CATEGORIES:
                row['category'] = record['category']
            for key in ('started_at', 'finished_at'):
                value = timestamp(record.get(key))
                if value:
                    row[key] = value
            duration = record.get('duration_seconds')
            if isinstance(duration, (float, int)) and not isinstance(duration, bool) and math.isfinite(duration) and duration >= 0:
                row['durationSeconds'] = duration
            rows.append(row)
    return {'schemaVersion': 1, 'asOf': today.isoformat(), 'retainedDays': 3,
            'purpose': '脱敏执行参考，成功与失败均保留，不替代原收据及业务验收', 'runs': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    today = dt.datetime.now(ZoneInfo('Asia/Shanghai')).date()
    history = ROOT / 'runtime/run_history'
    if history.is_symlink():
        raise ValueError('history-root-symlink')
    cutoff = today - dt.timedelta(days=2)
    candidates = [p for p in sorted(history.iterdir()) if p.is_dir()
                  and not p.is_symlink() and dated(p.name) and dated(p.name) < cutoff]
    report = {'asOf': today.isoformat(), 'cutoff': cutoff.isoformat(), 'apply': args.apply,
              'candidates': [p.name for p in candidates], 'archived': []}
    if args.apply:
        for directory in candidates:
            report['archived'].append(archive_day(ROOT, directory))
        reference = ROOT / 'docs/reference/recent-workflow-runs.json'
        reference.parent.mkdir(parents=True, exist_ok=True)
        reference.write_text(json.dumps(reference_rows(ROOT, today), ensure_ascii=False, indent=2) + '\n')
        report['reference'] = str(reference.relative_to(ROOT))
        receipt = ROOT / 'runtime/state/history-retention' / (today.isoformat() + '.json')
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()

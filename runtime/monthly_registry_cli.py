"""Versioned local maintenance for three monthly registries; never dispatches."""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from monthly_work_registry import METRICS, COUPON, INSPECTION, refresh, plan_sa, daily_plan

ROOT = Path(__file__).resolve().parent.parent
WORK_ITEMS = {METRICS: ['M%02d' % n for n in range(1, 12)],
              COUPON: ['coupon'], INSPECTION: ['inspection']}


def write_json(path, value):
    with path.open('x', encoding='utf-8') as handle:
        os.chmod(path, 0o600)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n');handle.flush();os.fsync(handle.fileno())


def publish(folder, snapshot, *, flow, month, today, sa=None, capacity=None):
    """Atomic latest pointer; completed generations are immutable local evidence."""
    if month != today.strftime('%Y-%m') or flow not in WORK_ITEMS:
        raise ValueError('registry-scope-mismatch')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (folder/'maintenance.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        latest = folder/'latest.json'; previous = None
        if latest.exists():
            pointer = json.loads(latest.read_text())
            generation = pointer.get('generation', '')
            if not re.fullmatch('[a-f0-9]{32}', generation):
                raise ValueError('registry-pointer-invalid')
            raw = (folder/generation/'registry.json').read_bytes()
            if hashlib.sha256(raw).hexdigest() != pointer['registrySha256']:
                raise ValueError('registry-integrity-mismatch')
            previous = json.loads(raw)
        registry = refresh(previous, snapshot, flow=flow, month=month, today=today)
        if sa is not None:
            registry = plan_sa(registry, sa, WORK_ITEMS[flow])
        daily = daily_plan(registry, today=today, capacity=capacity)
        generation = uuid.uuid4().hex; target = folder/generation
        target.mkdir(mode=0o700)
        temp_pointer = folder/('latest.'+generation+'.tmp')
        try:
            current_roster = [registry['merchants'][key]['record'] for key in registry['currentMerchantKeys']]
            for name, data in [('source.json', snapshot), ('current-roster.json', current_roster),
                               ('registry.json', registry), ('daily-plan.json', daily)]:
                write_json(target/name, data)
            hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in target.iterdir()}
            write_json(target/'manifest.json', {'flow': flow, 'month': month, 'sha256': hashes,
                                               'executionEnabled': False})
            write_json(temp_pointer, {'generation': generation, 'registrySha256': hashes['registry.json']})
            os.replace(temp_pointer, latest)
        except BaseException:
            temp_pointer.unlink(missing_ok=True)
            shutil.rmtree(target)
            raise
        return {'ok': True, 'flow': flow, 'month': month, 'generation': str(target),
                'latestSourceMerchants': sum(x['inLatestSource'] for x in registry['merchants'].values()),
                'eligible': sum(x['inLatestSource'] and x['eligible'] for x in registry['merchants'].values()),
                'planState': '待导入SA名单' if registry['plan'] is None else '本地计划已登记',
                'executionEnabled': False}


def main(flow, argv=None):
    if flow not in WORK_ITEMS:
        raise ValueError('unknown-workflow')
    now = datetime.now(ZoneInfo('Asia/Shanghai'))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--month', default=now.strftime('%Y-%m'))
    parser.add_argument('--sa', type=Path)
    parser.add_argument('--capacity', type=int)
    args = parser.parse_args(argv)
    folder = ROOT/'skills/workflows'/flow/'.runtime/monthly'/args.month
    snapshot = json.loads(args.snapshot.read_text())
    sa = json.loads(args.sa.read_text()) if args.sa is not None else None
    if args.sa is not None and sa is None:
        raise ValueError('sa-list-required')
    result = publish(folder, snapshot, flow=flow, month=args.month, today=now.date(), sa=sa, capacity=args.capacity)
    print(json.dumps(result, ensure_ascii=False))
    return 0

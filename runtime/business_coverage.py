"""Read original same-day inspection coverage; never rewrites technical outcomes."""
import json
from pathlib import Path
from receipt import parse_top_receipt_log

ROOT = Path(__file__).resolve().parent.parent
SUPPORTED = {'daily-new-stores-activity-audit-to-wechat',
             'daily-new-stores-decoration-audit-to-wechat'}


def assess_receipt(payload, day):
    shops = payload.get('shops')
    count = payload.get('targetCount')
    if (payload.get('day') != day or type(count) is not int or count < 0
            or not isinstance(shops, list) or len(shops) != count
            or any(not isinstance(shop, dict) for shop in shops)):
        return {'complete': False, 'reason': '当日门店覆盖证据不完整'}
    names = [shop.get('sourceName') for shop in shops]
    if any(not isinstance(name, str) or not name.strip() for name in names) or len(set(names)) != count:
        return {'complete': False, 'reason': '当日门店身份不完整或重复'}
    uncovered = []
    for shop in shops:
        status, reason = shop.get('status'), str(shop.get('reason', ''))
        if status in ('verified', 'already_verified', 'no-missing'):
            continue
        if status == 'skipped' and ':shop-not-operating:' in reason:
            continue
        uncovered.append({'name': shop['sourceName'], 'reason': reason or str(status)})
    complete = payload.get('status') == 'complete' and not uncovered
    return {'complete': complete, 'targets': count, 'uncovered': uncovered,
            'reason': (f'{len(uncovered)}家门店未检查' if uncovered else
                       ('当日检查证据完整' if complete else '原业务回执未完成'))}


def read_daily_coverage(flow, day, root=None):
    if flow not in SUPPORTED or day < '2026-10-27':
        return None
    root = Path(root) if root is not None else ROOT
    folder = (root / 'runtime/run_history' / day).resolve()
    candidates = []
    for record_path in folder.glob(flow + '--*--record.json'):
        try:
            if record_path.is_symlink() or record_path.resolve().parent != folder:
                continue
            record = json.loads(record_path.read_text())
            if record.get('skill') != flow or str(record.get('started_at', ''))[:10] != day:
                continue
            for name in reversed(record.get('logs') or []):
                log = Path(name)
                if (log.is_symlink() or log.resolve().parent != folder
                        or not log.name.startswith(flow + '--')):
                    continue
                payload = parse_top_receipt_log(log)
                if not payload or 'targetCount' not in payload or 'shops' not in payload:
                    continue
                result = assess_receipt(payload, day)
                result.update({'source': str(log), 'record': str(record_path),
                               'finished_at': record.get('finished_at', '')})
                candidates.append((record.get('finished_at', ''), result))
                break
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    if not candidates:
        return {'complete': False, 'reason': '缺少当日门店覆盖回执'}
    return max(candidates, key=lambda item: item[0])[1]

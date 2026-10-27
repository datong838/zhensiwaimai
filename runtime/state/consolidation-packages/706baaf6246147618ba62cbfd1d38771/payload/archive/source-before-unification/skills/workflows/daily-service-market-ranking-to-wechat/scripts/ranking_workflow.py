"""Original daily orchestration: frozen source -> original WeCom UI queue, once per day."""
import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[2]
STATE = BASE / '.runtime'
GROUP = '上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰'
FLOW = 'daily-service-market-ranking-ops'
NODE = os.environ.get('ZENSI_NODE', '/Users/ddt/.codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')
sys.path.insert(0, str(ROOT / 'skills/wechat-messaging/scripts'))
from ledger import atomic_json


def day_now():
    return datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')


def integrity():
    policy = json.loads((BASE / 'runtime-policy.json').read_text())
    expected = {'scripts/ranking_collector.mjs', 'scripts/ranking_workflow.py'}
    if (policy.get('files', {}).keys() != expected or policy.get('browserPort') != 9231
            or policy.get('groupName') != GROUP or policy.get('workflowId') != FLOW):
        raise ValueError('service-ranking-policy-mismatch')
    for name, sha in policy['files'].items():
        if hashlib.sha256((BASE / name).read_bytes()).hexdigest() != sha:
            raise ValueError('service-ranking-code-drift:' + name)
    from workflow_preflight import verify_dependencies
    verify_dependencies()


def capture(folder):
    process = subprocess.run([NODE, str(BASE / 'scripts/ranking_collector.mjs'), '--output', str(folder)],
                             capture_output=True, text=True, check=False)
    lines = [line for line in process.stdout.splitlines() if line.startswith('{')]
    if not lines:
        raise RuntimeError('service-ranking-collection-no-receipt:' + process.stderr[-400:])
    result = json.loads(lines[-1])
    if process.returncode or result.get('ok') is not True:
        raise RuntimeError(result.get('reason', 'service-ranking-collection-failed'))
    return result


def prior_outcome(prior):
    return {'ok': prior.get('state') == 'verified',
            'status': 'already_verified' if prior.get('state') == 'verified' else 'unknown',
            'reason': 'prior-attempt-requires-read-only-reconciliation' if prior.get('state') != 'verified' else None,
            'sendAttempts': 0, 'newSendAttempts': 0, 'prior': prior}


def frozen_item(day, folder, collect):
    frozen = folder / 'frozen.json'
    if frozen.exists():
        saved = json.loads(frozen.read_text())
    else:
        source = collect(folder / 'capture')
        stamp = datetime.fromisoformat(source['collectedAt'].replace('Z', '+00:00'))
        if source.get('browserPort') != 9231 or stamp.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d') != day:
            raise ValueError('service-ranking-source-date-invalid')
        data = Path(source['file']).read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        if sha != source.get('sha256'):
            raise ValueError('service-ranking-source-sha-mismatch')
        target = folder / (day + '-服务市场排名与考核指标.png')
        target.write_bytes(data)
        target.chmod(0o600)
        saved = {'day': day, 'collection': source, 'item': {'itemId': 'service-ranking', 'type': 'image',
                 'path': str(target), 'name': target.name, 'size': len(data), 'sha256': sha}}
        atomic_json(frozen, saved)
    item = saved['item']
    expected = folder / (day + '-服务市场排名与考核指标.png')
    if (saved.get('day') != day or Path(item['path']).resolve() != expected.resolve()
            or hashlib.sha256(expected.read_bytes()).hexdigest() != item['sha256']
            or expected.stat().st_size != item['size']):
        raise ValueError('service-ranking-frozen-binding-invalid')
    return item, saved['collection']


def run(*, execute=False, collect=capture, adapter=None):
    integrity()
    day = day_now()
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not execute:
        return {'ok': True, 'mode': 'capture-only', 'collection': collect(STATE / 'previews' / (day + '-' + str(uuid.uuid4()))), 'sendAttempts': 0}
    folder = STATE / 'days' / day
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker = folder / 'delivery.json'
    with (folder / 'run.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if marker.exists():
            return prior_outcome(json.loads(marker.read_text()))
        item, source = frozen_item(day, folder, collect)
        deadline = int(time.time()) + 600
        event = day + '-service-market-ranking'
        request = {'schemaVersion': 1, 'groupName': GROUP, 'items': [item],
                   'context': {'workflowId': FLOW, 'eventId': event, 'accountAlias': 'main-wechat',
                               'channel': 'desktop', 'deadlineAt': deadline}}
        atomic_json(folder / 'request.json', request)
        from wecom_adapter import WeComAdapter, target_preflight_verified
        transport = adapter or WeComAdapter()
        with transport.session(request):
            preflight = transport.preflight(request, folder / 'preflight')
            if not target_preflight_verified(preflight, GROUP):
                return {'ok': False, 'stage': 'preflight', 'reason': preflight.get('reason', 'target-preflight-failed'),
                        'sendAttempts': 0, 'collection': source}
            binding = {'eventId': event, 'groupName': GROUP, 'sha256': item['sha256'], 'name': item['name']}
            atomic_json(marker, binding | {'state': 'attempted', 'sendAttempts': None})
            grant = {'schemaVersion': 1, 'accountAlias': 'main-wechat', 'groupName': GROUP,
                     'channel': 'desktop', 'expiresAt': deadline,
                     'authorizationRef': 'user-20261026-service-market-ranking-daily'}
            try:
                delivery = transport.send_one(request, item, folder / 'send', grant, deadline)
            except BaseException as error:
                atomic_json(marker, binding | {'state': 'unknown', 'sendAttempts': None, 'reason': str(error)})
                raise
        verified = delivery.get('status') == 'verified'
        atomic_json(marker, binding | {'state': 'verified' if verified else 'unknown',
                                      'sendAttempts': delivery.get('sendAttempts'), 'delivery': delivery})
        result = {'ok': verified, 'stage': 'delivery', 'businessDate': day, 'collection': source,
                  'delivery': delivery, 'sendAttempts': delivery.get('sendAttempts'),
                  'reason': delivery.get('reason') if not verified else None, 'runtimeModelDecisions': 0}
        atomic_json(folder / 'result.json', result)
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    try:
        result = run(execute=args.execute)
    except Exception as error:
        result = {'ok': False, 'reason': str(error), 'stage': 'stopped'}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())

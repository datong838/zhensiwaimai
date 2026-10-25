"""Normal daily ledger node; original UI transport, one immutable daily attempt."""
import fcntl
import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
GROUP = '上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰'
WORKFLOW = 'daily-work-ledger'
CONTRACT = 'daily-final-ledger-v1'
FINAL = {'daily-agent-new-merchants-to-wechat',
         'taobao-flash-sale-negative-review-appeals',
         'meituan-waimai-negative-review-appeals-11'}


def local_now():
    return datetime.now(ZoneInfo('Asia/Shanghai'))


def readiness(now=None):
    """Read actual runs, never promote an unknown or a skipped-clock record."""
    import fixed_schedule
    from business_delivery_facts import read_fact
    now = now or local_now()
    if (now.hour, now.minute) < (18, 30):
        return False, ['final-slot-not-due']
    manifest = json.loads((ROOT / 'runtime/skills_manifest.json').read_text())
    enabled_names = {s['name'] for s in manifest['skills']
                     if s.get('enabled') and s.get('dev_state') == 'active'}
    required = FINAL | {'meituan-intelligent-customer-service'}
    if not required.issubset(enabled_names):
        return False, ['final-schedule-missing:' + name for name in sorted(required - enabled_names)]
    records = {}
    for path in (ROOT / 'runtime/run_history' / now.strftime('%Y-%m-%d')).glob('*--record.json'):
        record = json.loads(path.read_text())
        if 'cadence 内跳过' in record.get('detail', ''):
            continue
        records.setdefault(record.get('skill'), []).append(record)
    pending = []
    for skill in manifest['skills']:
        name = skill['name']
        if not skill.get('enabled') or skill.get('dev_state') != 'active':
            continue
        if fixed_schedule.customer_slot_superseded(name, now):
            continue
        if read_fact(name, now):
            continue
        cutoff = now.replace(hour=18 if name in FINAL else 17 if name in fixed_schedule.CUSTOMER_DUTY_HOURS else 0,
                             minute=30 if name in FINAL else 0, second=0, microsecond=0)
        completed = False
        for record in records.get(name, []):
            try:
                stamp = datetime.fromisoformat(record.get('finished_at', '')).replace(tzinfo=now.tzinfo)
            except (ValueError, TypeError):
                continue
            if record.get('status') == 'SUCCESS' and stamp.date() == now.date() and cutoff <= stamp <= now:
                completed = True
                break
        if not completed:
            pending.append(name)
    return not pending, pending


def directory(now):
    return ROOT / 'runtime/state/daily-ledger-delivery' / now.strftime('%Y-%m-%d')


def request_enabled(request, now=None):
    now = now or local_now()
    try:
        if not readiness(now)[0]:
            return False
        frozen = json.loads((directory(now) / 'request.json').read_text())
        if request != frozen or request.get('groupName') != GROUP:
            return False
        context = request['context']
        item, = request['items']
        source = directory(now) / (now.strftime('%Y-%m-%d') + '臻肆工作台账.xlsx')
        return (context.get('workflowId') == WORKFLOW and context.get('dailyLedgerContract') == CONTRACT
                and context.get('eventId') == now.strftime('%Y-%m-%d') + '-daily-work-ledger'
                and item.get('type') == 'file' and Path(item['path']).resolve() == source.resolve()
                and item.get('name') == source.name and item.get('size') == source.stat().st_size
                and item.get('sha256') == hashlib.sha256(source.read_bytes()).hexdigest())
    except (OSError, ValueError, KeyError, TypeError):
        return False


def deliver_once(path, *, adapter=None, now=None):
    now = now or local_now()
    ready, pending = readiness(now)
    if not ready:
        return {'status': 'blocked', 'sendAttempts': 0, 'reason': 'daily-ledger-not-ready', 'pending': pending}
    path = Path(path).resolve()
    expected = ROOT / 'work' / (now.strftime('%Y-%m-%d') + '臻肆工作台账.xlsx')
    if path != expected.resolve() or not path.is_file():
        return {'status': 'blocked', 'sendAttempts': 0, 'reason': 'daily-ledger-path-invalid'}
    sys.path.insert(0, str(ROOT / 'skills/wechat-messaging/scripts'))
    from ledger import atomic_json
    from wecom_adapter import WeComAdapter
    work = directory(now)
    work.mkdir(parents=True, exist_ok=True, mode=0o700)
    journal = work / 'delivery-journal.json'
    with (work / 'delivery.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if journal.exists():
            prior = json.loads(journal.read_text())
            return {'status': 'already_verified' if prior.get('state') == 'verified' else 'unknown',
                    'sendAttempts': 0, 'reason': 'daily-ledger-prior-attempt-no-resend'}
        source = work / path.name
        request_path = work / 'request.json'
        if request_path.exists():
            request = json.loads(request_path.read_text())
        else:
            data = path.read_bytes()
            source.write_bytes(data)
            item = {'itemId': 'daily-ledger', 'type': 'file', 'path': str(source),
                    'name': source.name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
            midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            request = {'schemaVersion': 1, 'groupName': GROUP, 'items': [item],
                       'context': {'workflowId': WORKFLOW, 'eventId': now.strftime('%Y-%m-%d') + '-daily-work-ledger',
                                   'dailyLedgerContract': CONTRACT, 'accountAlias': 'main-wechat',
                                   'channel': 'desktop', 'deadlineAt': midnight}}
            atomic_json(request_path, request)
        if not request_enabled(request, now):
            return {'status': 'blocked', 'sendAttempts': 0, 'reason': 'daily-ledger-frozen-binding-invalid'}
        transport = adapter or WeComAdapter()
        with transport.session(request):
            proof = transport.preflight(request, work / 'preflight')
            if not proof.get('ok') or proof.get('resolvedGroup') != GROUP or not proof.get('inputEmpty'):
                return {'status': 'blocked', 'sendAttempts': 0, 'reason': 'daily-ledger-preflight-failed'}
            atomic_json(journal, {'state': 'attempted', 'eventId': request['context']['eventId'],
                                  'sha256': request['items'][0]['sha256']})
            try:
                result = transport.send_one(request, request['items'][0], work / 'send',
                                            {'groupName': GROUP}, request['context']['deadlineAt'])
            except BaseException as error:
                atomic_json(journal, {'state': 'unknown', 'reason': type(error).__name__})
                raise
            atomic_json(journal, {'state': 'verified' if result.get('status') == 'verified' else 'unknown',
                                  'eventId': request['context']['eventId'], 'outcome': result})
            return result

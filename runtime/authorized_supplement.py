"""Explicitly authorized one-off continuation of original delivery nodes."""
import fcntl
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
GROUP = '上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰'
AUTH = 'user-20261024-three-supplements-once'
ALLOWED = {'daily-new-stores-opening-to-wechat':'text', 'daily-store-task-completion-ops':'image', 'contract-termination-ops':'image'}

def table():
    day = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d')
    return ROOT / 'runtime/state' / ('authorized-supplements-' + day + '.json')

def load_grant(workflow):
    if workflow not in ALLOWED:
        return None
    try:
        data = json.loads(table().read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    grant = data.get('grants', {}).get(workflow)
    if not grant:
        return None
    if (data.get('authorization') != AUTH or data.get('acceptedPossibleDuplicate') is not True
            or grant.get('groupName') != GROUP or grant.get('item', {}).get('type') != ALLOWED[workflow]
            or time.time() >= data.get('expiresAt', 0)):
        raise ValueError('supplement-authorization-invalid-or-expired')
    if workflow == 'daily-store-task-completion-ops':
        prerequisite = json.loads(Path(grant['requiredVerifiedMarker']).read_text())
        if prerequisite.get('state') != 'verified' or prerequisite.get('groupName') != GROUP:
            raise ValueError('supplement-detail-not-verified')
    item = grant['item']
    content = item['text'].encode() if item['type'] == 'text' else Path(item['path']).read_bytes()
    if hashlib.sha256(content).hexdigest() != item.get('sha256'):
        raise ValueError('supplement-payload-drift')
    if item['type'] != 'text' and (len(content) != item.get('size') or Path(item['path']).name != item.get('name')):
        raise ValueError('supplement-file-binding-invalid')
    return grant

def request_enabled(request):
    context = request.get('context', {})
    if context.get('supplementAuthorization') != AUTH:
        return False
    try:
        grant = load_grant(context.get('workflowId'))
        return bool(grant and request.get('groupName') == GROUP and context.get('eventId') == grant['eventId']
                    and request.get('items') == [grant['item']])
    except (OSError, ValueError, KeyError):
        return False

def deliver_once(workflow, run_dir, *, adapter=None):
    grant = load_grant(workflow)
    if grant is None:
        return None
    run = Path(run_dir).resolve()
    if not run.is_relative_to(Path(grant['runsRoot']).resolve()):
        return None
    sys.path.insert(0, str(ROOT / 'skills/wechat-messaging/scripts'))
    from ledger import atomic_json
    from wecom_adapter import WeComAdapter
    journal = Path(grant['journal'])
    journal.parent.mkdir(parents=True, exist_ok=True)
    binding = hashlib.sha256(json.dumps(grant, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with journal.with_suffix('.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if journal.exists():
            prior = json.loads(journal.read_text())
            if prior.get('binding') != binding:
                raise ValueError('supplement-journal-binding-conflict')
            if prior.get('state') == 'verified':
                return {'status':'already_verified','sendAttempts':0,'supplementReceipt':str(journal)}
            retry_file = journal.with_suffix('.explicit-retry.json')
            if not retry_file.exists():
                return {'status':'unknown','sendAttempts':0,'reason':'supplement-prior-attempt-no-resend','supplementReceipt':str(journal)}
            retry = json.loads(retry_file.read_text())
            if (workflow != 'contract-termination-ops' or retry.get('source') != 'explicit-user-cleared-draft-and-retry'
                    or retry.get('priorJournalSha256') != hashlib.sha256(journal.read_bytes()).hexdigest()
                    or retry.get('payloadSha256') != grant['item']['sha256']):
                raise ValueError('supplement-explicit-retry-invalid')
            reply_path = Path(retry['responsePath'])
            reply = json.loads(reply_path.read_text())
            result = reply['result']
            if (reply['taskId'] != retry['taskId'] or result.get('actualSuccessfulFinalActions') != 0
                    or result.get('inputEmpty') is not True or result.get('newMessageVisible') is not False
                    or result.get('resolvedGroup') != GROUP or result.get('sha256') != grant['item']['sha256']):
                raise ValueError('supplement-zero-action-proof-invalid')
            audit = journal.parent / 'explicit-retry-audit' / str(time.time_ns())
            audit.mkdir(parents=True, mode=0o700)
            (audit / 'original-journal.json').write_bytes(journal.read_bytes())
            (audit / 'original-response.json').write_bytes(reply_path.read_bytes())
            (audit / 'user-authorization.json').write_bytes(retry_file.read_bytes())
            retry_file.replace(audit / 'consumed-authorization.json')

        deadline = min(time.time() + 840, json.loads(table().read_text())['expiresAt'])
        request = {'schemaVersion':1,'groupName':GROUP,'items':[grant['item']],
                   'context':{'workflowId':workflow,'eventId':grant['eventId'],'accountAlias':'main-wechat',
                              'channel':'desktop','deadlineAt':deadline,'supplementAuthorization':AUTH}}
        transport = adapter or WeComAdapter()
        with transport.session(request):
            preflight = transport.preflight(request, run / 'authorized-supplement/preflight')
            if preflight.get('ok') is not True or preflight.get('resolvedGroup') != GROUP:
                return {'status':'blocked','sendAttempts':0,'reason':preflight.get('reason','supplement-preflight-failed')}
            atomic_json(journal, {'state':'attempted','binding':binding,'eventId':grant['eventId'],
                                 'authorization':AUTH,'originalMarkerPreserved':True})
            try:
                outcome = transport.send_one(request, grant['item'], run / 'authorized-supplement/send',
                    {'authorizationRef':AUTH,'groupName':GROUP,'expiresAt':deadline,'accountAlias':'main-wechat','channel':'desktop'}, deadline)
            except BaseException as error:
                atomic_json(journal,{'state':'unknown','binding':binding,'reason':str(error),'originalMarkerPreserved':True})
                raise
            atomic_json(journal,{'state':'verified' if outcome.get('status')=='verified' else 'unknown',
                       'binding':binding,'eventId':grant['eventId'],'authorization':AUTH,
                       'originalMarkerPreserved':True,'outcome':outcome})
            return outcome | {'supplementReceipt':str(journal),'originalMarkerPreserved':True}

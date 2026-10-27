#!/usr/bin/env python3
"""Unified WeChat messaging entrypoint. Receiving is deliberately unsupported in v1."""
from __future__ import annotations
import argparse
import json
import os
import shutil
import signal
import sys
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path
from contract import (Rejected, check_grant, digest, event_key, file_hash, item_key,
                      normalize, request_digest)
from ledger import atomic_json, event_lock, read_json

ROOT = Path(__file__).resolve().parents[1]
# 2026-10-24 测试隔离（fail-safe 单点翻转，与 WECHAT_TEST_GROUP 对称）：设置
# WECOM_TEST_ROOT 后，本执行器的全部标记/账本（delivery.json、preflight、receipts）
# 写入独立目录（默认 .runtime-test），绝不触碰生产 .runtime。仅运行期环境变量生效，
# 不写任何配置文件；变量不存在时回退到 .runtime，对明天生产流零影响。
_STATE_NAME = os.environ.get('WECOM_TEST_ROOT') or '.runtime'
STATE = ROOT / _STATE_NAME
CAPABILITIES = {'desktop': {'text': 'candidate', 'image': 'candidate', 'file': 'candidate', 'video': 'unsupported'},
                'mobile': {'text': 'candidate', 'image': 'candidate', 'file': 'candidate', 'video': 'unsupported'},
                'receive': 'unsupported', 'verifyExistingFiles': 'implemented-read-only',
                'automaticRestart': 'unsupported'}


@contextmanager
def deadline(until):
    remaining = until - time.time()
    if remaining <= 0:
        raise Rejected('deadline-expired')
    def expired(*_):
        raise TimeoutError('deadline-expired')
    old = signal.signal(signal.SIGALRM, expired)
    old_timer = signal.setitimer(signal.ITIMER_REAL, remaining)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *old_timer)
        signal.signal(signal.SIGALRM, old)


def verify_dependencies():
    manifest = read_json(ROOT / 'dependencies.json')
    if not manifest or not manifest.get('files'):
        raise Rejected('dependency-manifest-missing')
    for name, expected in manifest['files'].items():
        p = Path(name)
        if not p.is_absolute():
            p = ROOT / p
        if not p.is_file() or file_hash(p) != expected:
            raise Rejected('dependency-drift:' + str(p))
    return True


def runtime_gate(request, grant):
    verify_dependencies()
    policy = read_json(ROOT / 'runtime-policy.json')
    if policy.get('mode') != 'acceptance':
        raise Rejected('runtime-offline-awaiting-acceptance')
    if (request['groupName'] != policy.get('groupName')
        or request_digest(request) not in policy.get('requestDigests', [])
        or grant['authorizationRef'] != policy.get('authorizationRef')
        or time.time() >= policy.get('expiresAt', 0)):
        raise Rejected('acceptance-scope-mismatch')


def freeze_item(item, work, *, allow_refreeze=False):
    if item['type'] == 'text':
        return dict(item)
    frozen = work / 'payload' / item['name']
    frozen.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if frozen.exists() and allow_refreeze:
        # 事件从未发出（prior/delivery.json 不存在）但早前失败档留下了旧冻结字节
        # （上游产物每轮重生成，xlsx 内嵌时间戳 sha 必变）→ 重冻结为当前请求字节。
        # 仅在调用方证明该 item 零发送历史时才允许；attempted/verified 一律保持钉死。
        frozen.chmod(0o600)
        frozen.unlink()
    if not frozen.exists():
        with Path(item['path']).open('rb') as source, frozen.open('xb') as target:
            os.chmod(frozen, 0o600)
            shutil.copyfileobj(source, target)
            target.flush(); os.fsync(target.fileno())
        os.chmod(frozen, 0o400)
    if file_hash(frozen) != item['sha256'] or frozen.stat().st_size != item['size']:
        raise Rejected('frozen-payload-mismatch')
    return item | {'path': str(frozen)}


def review_summary(review, total_elapsed_ms, status):
    """Code-generated execution retrospective; never invents unrun phases."""
    failed=[{'stage':row['stage'],'status':row.get('status'),'pitfalls':row.get('pitfalls',[])}
            for row in review if row.get('status')!='completed']
    return {'totalElapsedMs':total_elapsed_ms, 'result':status,
            'stageCount':len(review),
            'completedStages':sum(row.get('status')=='completed' for row in review),
            'failedStages':failed}


def deliver(request, grant, root, adapter, *, reconcile=False, rebind_event=False):
    """Internal engine; CLI enforces release policy before constructing live adapter."""
    started = time.monotonic()
    owner_lifetime = getattr(adapter, 'owner_lifetime', False) is True
    def pending_image(item, state):
        return (owner_lifetime and item['type'] == 'image' and state
                and state.get('status') == 'unknown' and state.get('sendAttempts') == 1
                and state.get('resolvedGroup') == request['groupName']
                and state.get('inputEmpty') is True
                and state.get('backend') == 'system-events-ui-tree'
                and state.get('reason') == 'native-ui-inline-image-not-exposed')
    result = {'ok': False, 'status': 'blocked', 'groupName': request['groupName'],
              'channel': request['context']['channel'], 'requestDigest': request_digest(request),
              'runtimeModelDecisions': 0, 'items': [], 'review': []}
    def stage(name, fn):
        t = time.monotonic()
        row = {'stage': name, 'status': 'running', 'pitfalls': []}
        result['review'].append(row)
        try:
            v = fn(); row['status'] = 'completed'; return v
        except Exception as e:
            row.update(status='failed', pitfalls=[str(e)]); raise
        finally:
            row['elapsedMs'] = round((time.monotonic()-t)*1000)
    try:
        stage('authorization', lambda: check_grant(request, grant, enforce_expiry=not owner_lifetime))
        if request['context']['channel'] != adapter.channel or any(i['type'] not in adapter.supported for i in request['items']):
            raise Rejected('unsupported-channel-or-type')
        with event_lock(root, request, rebind=rebind_event) as directory:
            prepared = []
            # Inspect the entire batch before UI: no earlier items sent if a later one conflicts.
            for item in request['items']:
                work = directory / item_key(request, item)
                work.mkdir(exist_ok=True, mode=0o700)
                prior = read_json(work / 'delivery.json')
                if prior and prior.get('sha256') != item['sha256']:
                    raise Rejected('ledger-payload-conflict')
                frozen = stage('freeze:' + item['itemId'],
                               lambda i=item,w=work,ok=prior is None: freeze_item(i,w,allow_refreeze=ok))
                prepared.append((frozen,work,prior))
            if all(p and p.get('status') == 'verified' for _,_,p in prepared):
                result.update(ok=True, status='already_verified', items=[p for _,_,p in prepared])
                return result
            if any(p and p.get('status') in ('attempted','unknown') and not pending_image(i,p)
                   for i,_,p in prepared) and not reconcile:
                result['review'].append({'stage':'deduplication','status':'blocked',
                                         'elapsedMs':0,
                                         'pitfalls':['existing-attempt-reconcile-only']})
                result.update(status='unknown', reason='existing-attempt-reconcile-only',
                              items=[p for _,_,p in prepared if p])
                return result
            if not reconcile and all(p and (p.get('status') == 'verified' or pending_image(i,p)) for i,_,p in prepared):
                result.update(status='partial' if any(p['status']=='verified' for _,_,p in prepared) else 'unknown',
                              items=[p for _,_,p in prepared], executionComplete=True,
                              verificationPending=[i['itemId'] for i,_,p in prepared if pending_image(i,p)],
                              reason='image-submission-awaits-read-only-verification')
                return result
            with (nullcontext() if owner_lifetime else deadline(request['context']['deadlineAt'])), adapter.session(request):
                preflight = stage('preflight', lambda: adapter.preflight(request, directory/'preflight'))
                if preflight.get('ok') is not True:
                    raise Rejected(preflight.get('reason','preflight-failed'))
                for item,work,prior in prepared:
                    if prior and prior.get('status') == 'verified':
                        result['items'].append(prior); continue
                    if not reconcile and pending_image(item,prior):
                        result['items'].append(prior); continue
                    if reconcile and not prior:
                        raise Rejected('reconcile-no-attempt')
                    claim = {'itemId': item['itemId'], 'sha256': item['sha256'],
                             'type': item['type'], 'status': 'attempted', 'claimedAt': time.time()}
                    if not reconcile:
                        # Persist conservative intent before calling any transport code.
                        atomic_json(work/'delivery.json', claim)
                    try:
                        if reconcile:
                            outcome = stage('reconcile:'+item['itemId'], lambda: adapter.reconcile(request,item,work,prior))
                        else:
                            check_grant(request, grant, enforce_expiry=not owner_lifetime)
                            outcome = stage('send:'+item['itemId'], lambda: adapter.send_one(request,item,work,grant,request['context']['deadlineAt']))
                        current = (prior if reconcile else claim) | outcome
                        if current.get('status') == 'verified':
                            current.pop('reason', None)
                        if current['status'] not in ('verified','unknown','blocked'):
                            raise Rejected('adapter-outcome-invalid')
                        if current['status'] == 'blocked' and current.get('sendAttempts') != 0:
                            current['status'] = 'unknown'
                    except BaseException as error:
                        # Interrupt, timeout, transport crash and missing receipts all stay unknown.
                        current = (prior if reconcile else claim) | {'status':'unknown', 'reason':str(error), 'sendAttempts':None}
                        atomic_json(work/'delivery.json', current)
                        result['items'].append(current)
                        raise
                    atomic_json(work/'delivery.json', current)
                    result['items'].append(current)
                    if current['status'] != 'verified' and not (not reconcile and pending_image(item,current)):
                        result.update(status='partial' if any(x['status']=='verified' for x in result['items']) else current['status'],
                                      reason=current.get('reason'))
                        return result
                pending = [i['itemId'] for i,_,_ in prepared
                           if any(r.get('itemId') == i['itemId'] and pending_image(i,r) for r in result['items'])]
                if pending:
                    result.update(status='partial' if any(x['status']=='verified' for x in result['items']) else 'unknown',
                                  executionComplete=True, verificationPending=pending,
                                  reason='image-submission-awaits-read-only-verification')
                else:
                    result.update(ok=True, status='verified')
    except Exception as error:
        result['reason'] = str(error)
        if any(i['status']=='verified' for i in result['items']):
            result['status'] = 'partial'
        elif any(i['status']=='unknown' for i in result['items']):
            result['status'] = 'unknown'
    finally:
        result['elapsedMs'] = round((time.monotonic()-started)*1000)
        result['eventKey'] = event_key(request)
        result['reviewSummary'] = review_summary(result['review'], result['elapsedMs'], result['status'])
        atomic_json(Path(root)/'receipts'/f'{time.time_ns()}.json', result)
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=('capabilities','validate','preflight','verify-existing','execute','reconcile','receive'))
    p.add_argument('--request'); p.add_argument('--authorization')
    p.add_argument('--device-serial-file')
    args = p.parse_args()
    try:
        if args.action == 'capabilities':
            verify_dependencies()
            output = {'ok':True, 'capabilities':CAPABILITIES, 'policy':read_json(ROOT/'runtime-policy.json')}
        elif args.action == 'receive':
            output = {'ok':False, 'status':'unsupported', 'reason':'receive-not-implemented'}
        else:
            request = normalize(read_json(args.request))
            if args.action == 'validate':
                output = {'ok':True, 'mode':'offline-validation', 'requestDigest':request_digest(request),
                          'eventKey':event_key(request), 'supported':request['context']['channel']=='desktop' and all(i['type']!='video' for i in request['items']),
                          'items':[{k:v for k,v in i.items() if k not in ('text','path')} for i in request['items']]}
            elif args.action in ('preflight', 'verify-existing'):
                verify_dependencies()
                if request['context']['channel'] != 'desktop':
                    raise Rejected('unsupported-preflight-channel')
                from desktop_adapter import DesktopAdapter
                adapter = DesktopAdapter()
                with deadline(request['context']['deadlineAt']), adapter.session(request):
                    if args.action == 'verify-existing':
                        from history_verify import verify_existing_files
                        work = STATE/'history-verification'/str(time.time_ns())
                        output = verify_existing_files(request, adapter, work)
                        atomic_json(work/'receipt.json', output)
                        output['receiptPath'] = str(work/'receipt.json')
                    else:
                        output = adapter.preflight(request, STATE/'preflight'/str(time.time_ns()))
                        output = output | {'sendAttempts':0, 'mode':'preflight-no-send'}
            else:
                grant = read_json(args.authorization)
                check_grant(request, grant)
                runtime_gate(request, grant)
                if any(i['type']=='video' for i in request['items']):
                    raise Rejected('unsupported-channel-or-type')
                if request['context']['channel']=='mobile':
                    if not args.device_serial_file:raise Rejected('mobile-device-binding-required')
                    serial=Path(args.device_serial_file).read_text().strip()
                    import hashlib
                    policy=read_json(ROOT/'runtime-policy.json')
                    if hashlib.sha256(serial.encode()).hexdigest()[:12]!=policy.get('deviceHash') or policy.get('userId')!=0:
                        raise Rejected('mobile-device-policy-mismatch')
                    from mobile_adapter import MobileAdapter
                    adapter=MobileAdapter(serial)
                else:
                    from desktop_adapter import DesktopAdapter
                    adapter=DesktopAdapter()
                output = deliver(request, grant, STATE, adapter, reconcile=args.action=='reconcile')
        print(json.dumps(output, ensure_ascii=False))
        return 0 if output.get('ok') else 1
    except Exception as error:
        print(json.dumps({'ok':False, 'status':'blocked', 'reason':str(error), 'sendAttempts':0}, ensure_ascii=False))
        return 1

if __name__ == '__main__':
    raise SystemExit(main())

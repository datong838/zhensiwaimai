"""Resume an exact existing two-file batch through the original shared engine."""
import fcntl
import hashlib
import json
import re
import time
from pathlib import Path


def native_unknown(prior):
    return (prior.get('status') == 'unknown' and prior.get('sendAttempts') == 1
            and prior.get('backend') == 'system-events-ui-tree'
            and prior.get('reason') == 'native-ui-file-card-not-confirmed'
            and type(prior.get('claimedAt')) in (int, float)
            and 0 <= time.time() - prior['claimedAt'] < 7200)


def native_task_matches(task, intent, request, item, claimed_at):
    bare = {k: v for k, v in task.items() if k != 'binding'}
    binding = hashlib.sha256(json.dumps(bare, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    original = task.get('request', {})
    identity = lambda value: {k: value.get(k) for k in ('itemId', 'type', 'name', 'size', 'sha256')}
    return (task.get('stage') == 'send' and task.get('binding') == binding
            and original.get('groupName') == request.get('groupName')
            and all(original.get('context', {}).get(k) == request.get('context', {}).get(k)
                    for k in ('workflowId', 'eventId', 'accountAlias', 'channel'))
            and identity(task.get('item') or {}) == identity(item)
            and [identity(value) for value in original.get('items', [])]
                == [identity(value) for value in request.get('items', [])]
            and intent.get('taskId') == task.get('taskId') and intent.get('binding') == binding
            and intent.get('sha256') == item.get('sha256')
            and abs(intent.get('at', 0) - claimed_at) < 120)


def native_visible_frame(request, item, ui):
    from file_size_policy import displayed_size_matches
    _, anchors = ui.read_anchors('conversationTitle', 'composer')
    if anchors['conversationTitle']['value'] != request['groupName'] or anchors['composer']['value'] != '':
        raise ValueError('native-readback-target-or-draft-mismatch')
    root = json.loads(ui.SELECTORS.read_text())['anchors']['messages']['path']
    nodes = ui.execute(root_path=root, max_depth=4)['nodes']
    rows = [node['path'] for node in nodes if node.get('role') == 'AXRow']
    matches = []
    for row in rows:
        values = [node.get('value') for node in nodes if node.get('path', [])[:len(row)] == row]
        if item['name'] not in values:
            continue
        sizes = [v for v in values if isinstance(v, str) and re.fullmatch(r'\d+(?:\.\d+)?K', v)]
        if len(sizes) != 1 or not displayed_size_matches(item['size'], sizes[0]):
            raise ValueError('native-readback-file-size-mismatch')
        matches.append({'messagePath': row, 'visibleFileName': item['name'], 'visibleFileSize': sizes[0]})
    if len(matches) != 1:
        raise ValueError('native-readback-file-not-unique')
    # Recheck after reading the pane: a concurrent user edit or group change fails closed.
    _, end = ui.read_anchors('conversationTitle', 'composer')
    if end['conversationTitle']['value'] != request['groupName'] or end['composer']['value'] != '':
        raise ValueError('native-readback-target-or-draft-mismatch')
    return matches[0] | {'verified': True, 'groupName': request['groupName'], 'inputEmpty': True,
                         'observedAt': time.time()}


def native_file_proof(request, item, claimed_at, *, queue=None, ui=None):
    """Read current native file cards only; never navigate, activate, click or send."""
    if ui is None:
        import native_ui_post as ui
    queue = Path(queue) if queue is not None else ui.QUEUE
    identity = {k: item[k] for k in ('name', 'size', 'sha256')}
    try:
        if (request.get('context', {}).get('workflowId') != 'jinsha-reports'
                or item.get('type') != 'file' or not item['name'].endswith('.xlsx')
                or not 0 <= time.time() - claimed_at < 7200):
            raise ValueError('native-readback-scope-invalid')
        source = Path(item['path']); data = source.read_bytes()
        if source.name != identity['name'] or len(data) != identity['size'] or hashlib.sha256(data).hexdigest() != identity['sha256']:
            raise ValueError('native-readback-source-mismatch')
        matches = []
        for file in queue.glob('*/task.json'):
            try:
                task = json.loads(file.read_text()); intent = json.loads(file.with_name('send-intent.json').read_text())
                if native_task_matches(task, intent, request, item, claimed_at):
                    matches.append(task)
            except (OSError, ValueError, TypeError):
                continue
        if len(matches) != 1:
            raise ValueError('native-readback-original-intent-not-unique')
        frames = [native_visible_frame(request, item, ui)]
        time.sleep(.4)
        frames.append(native_visible_frame(request, item, ui))
        if any(frames[0][k] != frames[1][k] for k in ('messagePath', 'visibleFileName', 'visibleFileSize')):
            raise ValueError('native-readback-frames-changed')
        return {'result': 'verified', 'resolvedGroup': request['groupName'], 'item': identity,
                'frames': frames, 'originalTaskId': matches[0]['taskId'],
                'originalTaskBinding': matches[0]['binding'], 'backend': 'system-events-ui-tree',
                'newSendAttempts': 0, 'readOnly': True}
    except (OSError, ValueError, RuntimeError) as error:
        return {'result': 'not-verified', 'reason': str(error), 'newSendAttempts': 0, 'readOnly': True}


def verify_legacy_sent_file(adapter, request, item, outcome, started, *, native_mode):
    # Native UI sends already carry their own proof. Never invoke the old AX reader.
    if native_mode or outcome.get('sendAttempts') != 1 or (outcome.get('transport') or {}).get('sent') is not True:
        return outcome
    proc=adapter._run_sender(['verify-file','--group',request['groupName'],'--file',item['path'],'--sent-after-unix',str(started)])
    proof=adapter._parse_receipt(proc)
    if (not proc.returncode and proof and proof.get('result')=='verified'
        and proof.get('resolvedGroup')==request['groupName']
        and proof.get('item')=={k:item[k] for k in ('name','size','sha256')}):
        return outcome|{'status':'verified','verificationLevel':'file-name-size-ui','evidence':proof,'reason':None}
    return outcome|{'status':'unknown','reason':'file-card-readback-unconfirmed'}


def eligible(prior, request, directory, item_key, read_json):
    if prior.get('bridgeVersion') != 1 or prior.get('state') not in ('unknown', 'partial'):
        return False
    if len(request['items']) != 2 or any(i['type'] != 'file' for i in request['items']):
        return False
    first, second = request['items']
    a = read_json(directory / item_key(request, first) / 'delivery.json')
    b = read_json(directory / item_key(request, second) / 'delivery.json')
    if not a or a.get('sha256') != first['sha256']:
        return False
    if b is not None:
        return (a.get('status') == 'verified' and a.get('verificationLevel') == 'file-name-size-ui'
                and b.get('sha256') == second['sha256'] and b.get('status') == 'unknown'
                and b.get('sendAttempts') == 1 and ((b.get('transport') or {}).get('sent') is True or native_unknown(b)))
    if a.get('status') == 'verified':
        return a.get('verificationLevel') == 'file-name-size-ui' and prior.get('resumeUnattempted') is True
    transport = a.get('transport') or {}
    if native_unknown(a):
        return True
    return (a.get('status') == 'unknown' and a.get('sendAttempts') == 1
            and a.get('reason') == 'wecom-tail-unconfirmed'
            and transport.get('sent') is True
            and (transport.get('receipt') or {}).get('result') == 'sent-tail-unconfirmed'
            and 0 <= time.time() - a.get('claimedAt', 0) < 7200)


def recover(cmd, *, verify_only):
    import workflow_bridge as bridge
    from contract import item_key
    from executor import deliver
    from ledger import read_json, atomic_json, event_lock
    from wecom_adapter import WeComAdapter, ui_tree_only_required
    # Reconstruct using the same CLI parser contract; prepare checks route,
    # authorization, filenames, frozen bytes and business binding.
    parser = bridge.argparse.ArgumentParser()
    for k in ('workflow-id','group','payload-type','authorization','ledger','marker-name','output-dir'):
        parser.add_argument('--'+k, required=True)
    parser.add_argument('--item',action='append',required=True)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--deadline-unix',type=float)
    parser.add_argument('--correction-v1',action='store_true')
    args = parser.parse_args(cmd[2:])
    request, grant = bridge.prepare(args)
    if args.workflow_id != 'jinsha-reports':
        raise ValueError('recovery-workflow-mismatch')
    bridge.verify_pre_dispatch_dependencies()
    marker = Path(args.ledger)/args.marker_name
    if not marker.exists():
        return None
    with marker.with_suffix('.bridge.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        prior = read_json(marker)
        bridge.check_old(prior,request)
        root = marker.parent/'.wechat-messaging'
        class RecoveryAdapter(WeComAdapter):
            def send_one(self, request, item, work, grant, deadline):
                started=time.time()
                outcome=super().send_one(request,item,work,grant,deadline)
                return verify_legacy_sent_file(self,request,item,outcome,started,native_mode=ui_tree_only_required())
        adapter = RecoveryAdapter()
        with event_lock(root,request) as directory:
            if not eligible(prior,request,directory,item_key,read_json):
                return None
            current_items=[]
            for first in request['items']:
                target = directory/item_key(request,first)/'delivery.json'
                current = read_json(target)
                if current is None:
                    continue
                if current['status'] != 'verified':
                    with adapter.session(request):
                        if ui_tree_only_required():
                            proof=native_file_proof(request,first,current['claimedAt'])
                            failed=False
                        else:
                            preflight=adapter.preflight(request,directory/'recovery-preflight')
                            if preflight.get('ok') is not True:
                                return None
                            proc=adapter._run_sender(['verify-file','--group',request['groupName'],'--file',first['path'],'--sent-after-unix',str(current['claimedAt'])])
                            proof=adapter._parse_receipt(proc)
                            failed=proc.returncode != 0
                        atomic_json(directory/'readback-recovery-last.json',proof or {'error':'readback-proof-missing'})
                        if (failed or not proof or proof.get('result')!='verified'
                                or proof.get('resolvedGroup')!=request['groupName']
                                or proof.get('item')!={k:first[k] for k in ('name','size','sha256')}):
                            return None
                    audit=directory/('readback-recovery-'+str(time.time_ns()))
                    audit.mkdir(mode=0o700)
                    atomic_json(audit/'original-marker.json',prior)
                    atomic_json(audit/'original-delivery.json',current)
                    atomic_json(audit/'proof.json',proof)
                    current=current|{'status':'verified','verificationLevel':'file-name-size-ui',
                                     'reconciledWithoutSend':True,'evidence':proof,'reconciledAt':time.time()}
                    current.pop('reason',None)
                    atomic_json(target,current)
                current_items.append(current)
            complete=len(current_items)==2 and all(i['status']=='verified' for i in current_items)
            prior=prior|{'state':'verified' if complete else 'partial','verified':complete,'ok':complete,
                         'resumeUnattempted':not complete,'reconciledWithoutSend':True,
                         'reason':None if complete else 'verified-prefix-unattempted-suffix','commonReceipt':
                         (prior.get('commonReceipt') or {})|{'items':current_items,'ok':complete,'status':'verified' if complete else 'partial'}}
            atomic_json(marker,prior)
        if verify_only or prior.get('verified'):
            return prior|{'newSendAttempts':0}
        # deliver rechecks authorization and the complete original event binding,
        # reuses the verified first item, and journals intent BEFORE sending item 1.
        common=deliver(request,grant,root,adapter)
        items=common.get('items',[])
        attempts=[i.get('sendAttempts') for i in items]
        result=prior|{'ok':common['ok'],'verified':common['ok'],
            'state':'verified' if common['ok'] else common['status'],
            'sendAttempts':None if any(x is None for x in attempts) else sum(attempts),
            'recoveredVerifiedPrefix':True,
            'newSendAttempts':sum((x.get('sendAttempts') or 0) for x in items if x.get('itemId')!='0'),
            'reason':common.get('reason'),'commonReceipt':common,'resumeUnattempted':False,
            'sendReview':bridge.compatible_review(common),'elapsedMs':common['elapsedMs']}
        atomic_json(marker,result)
        return result

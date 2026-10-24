"""Resume an exact existing two-file batch through the original shared engine."""
import fcntl
import json
import time
from pathlib import Path


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
                and b.get('sendAttempts') == 1 and (b.get('transport') or {}).get('sent') is True)
    if a.get('status') == 'verified':
        return a.get('verificationLevel') == 'file-name-size-ui' and prior.get('resumeUnattempted') is True
    transport = a.get('transport') or {}
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
    from wecom_adapter import WeComAdapter
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
                if outcome.get('sendAttempts') != 1 or (outcome.get('transport') or {}).get('sent') is not True:
                    return outcome
                proc=self._run_sender(['verify-file','--group',request['groupName'],'--file',item['path'],'--sent-after-unix',str(started)])
                proof=self._parse_receipt(proc)
                if (not proc.returncode and proof and proof.get('result')=='verified'
                    and proof.get('resolvedGroup')==request['groupName']
                    and proof.get('item')=={k:item[k] for k in ('name','size','sha256')}):
                    return outcome|{'status':'verified','verificationLevel':'file-name-size-ui',
                                   'evidence':proof,'reason':None}
                return outcome|{'status':'unknown','reason':'file-card-readback-unconfirmed'}
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
                        preflight=adapter.preflight(request,directory/'recovery-preflight')
                        if preflight.get('ok') is not True:
                            return None
                        proc=adapter._run_sender(['verify-file','--group',request['groupName'],'--file',first['path'],'--sent-after-unix',str(current['claimedAt'])])
                        proof=adapter._parse_receipt(proc)
                        atomic_json(directory/'readback-recovery-last.json',proof or {'error':proc.stderr,'stdout':proc.stdout})
                        if (proc.returncode or not proof or proof.get('result')!='verified'
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

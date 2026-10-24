"""Read-only file delivery reconciliation for original workflow CLI entrypoints."""
import fcntl
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from ledger import atomic_json
from wecom_adapter import WeComAdapter


def reconcile_run(run_arg, *, runs, events, group, event_suffix, whole_flow):
    run=Path(run_arg).resolve();root=Path(runs).resolve()
    if not run.is_relative_to(root) or run==root or run.is_symlink():
        raise ValueError('reconcile-run-outside-owned-root')
    day=run.name[:10]
    if day!=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat():
        raise ValueError('reconcile-run-not-today')
    original=(run/'summary.json').read_bytes();summary=json.loads(original)
    file=Path(summary['reportPath']).resolve()
    if not file.is_relative_to(run) or file.name!=summary['report'] or summary['day']!=day:
        raise ValueError('reconcile-summary-path-binding-invalid')
    event=f'{day}-{event_suffix}';marker=Path(events)/f'{event}.json'
    with marker.with_suffix('.reconcile.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        prior=json.loads(marker.read_text());digest=hashlib.sha256(file.read_bytes()).hexdigest()
        if prior.get('event')!=event or prior.get('groupName')!=group or prior.get('name')!=file.name or prior.get('sha256')!=digest:
            raise ValueError('reconcile-original-marker-binding-invalid')
        if prior.get('state')=='verified':
            return {'status':'already_verified','event':event,'sendAttempts':0,'reconciledWithoutSend':True}
        since=int(run.name.rsplit('-',1)[1])/1e9
        if datetime.fromtimestamp(since,ZoneInfo('Asia/Shanghai')).date().isoformat()!=day:
            raise ValueError('reconcile-original-run-timestamp-invalid')
        request={'groupName':group,'context':{'deadlineAt':time.time()+180,'reconcileSince':since}}
        adapter=WeComAdapter();work=run/'readonly-reconciliation'
        with adapter.session(request):
            # The global transport lock also serializes the original workflows.
            if json.loads(marker.read_text())!=prior:
                raise ValueError('reconcile-marker-changed')
            outcome=adapter.reconcile(request,{'type':'file','path':str(file)},work,prior)
            if outcome.get('status')!='verified':return outcome|{'event':event}
            audit=work/str(time.time_ns());audit.mkdir(parents=True,mode=0o700)
            (audit/'original-marker.json').write_bytes(marker.read_bytes())
            (audit/'original-summary.json').write_bytes(original)
            atomic_json(marker,prior|{'state':'verified','verificationLevel':outcome['verificationLevel'],
                        'evidence':outcome['evidence'],'reconciledWithoutSend':True,'reconcileReceipt':str(work/'reconcile-proof.json')})
            result=summary|{'status':'verified' if whole_flow else 'detail-verified-image-pending',
                            'reconciledWithoutSend':True,'newSendAttempts':0,'fileReconciliation':outcome,'reason':None}
            atomic_json(run/'summary.json',result)
            return result

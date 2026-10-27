#!/usr/bin/env python3
"""One invocation, deterministic collection/audit/phone/commit workflow."""
import argparse
import json
import time
import uuid
import fcntl
from pathlib import Path
from types import SimpleNamespace
import structured_merchant_collector as collector
import wechat_sender_executor as sender
import desktop_wechat_sender
import executor_integrity
import runtime_contract

WORKFLOW_RUNS_ROOT = Path(__file__).resolve().parents[4] / "runs"

def _receipt_matches_item(receipt, item, group):
    payloads = receipt.get("payloads") or []
    wrapped_unknown = (receipt.get("stage") == "completed"
                       and (receipt.get("commonReceipt") or {}).get("status") == "unknown")
    return (receipt.get("bridgeVersion") == 1
            and receipt.get("state") == "unknown"
            and receipt.get("sendAttempts") == 1
            and receipt.get("physicalSendAttempts") == 1
            and (receipt.get("stage") == "post_send_verify" or wrapped_unknown)
            and receipt.get("groupName") == group
            and len(payloads) == 1
            and payloads[0].get("text") == item["text"]
            and payloads[0].get("sha256") == item["sha256"])

def recover_unknown_marker_from_receipt(item, group):
    """Recover only a uniquely bound nonzero marker from private unknown receipts."""
    marker = sender.STATE_DIR / 'send-attempts' / (sender.send_identity(group, item) + '.json')
    prior = None
    if marker.exists():
        try:
            prior = json.loads(marker.read_text())
        except (OSError, json.JSONDecodeError):
            return marker, False
        # A complete binding must be left untouched; only an incomplete legacy
        # marker is eligible for code-owned enrichment from a matching receipt.
        if (prior.get('groupName') == group and prior.get('merchantId') == item['merchantId']
                and prior.get('messageSha256') == item['sha256'] and prior.get('payloads')
                and prior.get('sendAttempts') == 1 and prior.get('state') in ('unknown', 'verified')):
            return marker, False
        if not (prior.get('state') == 'unknown' and prior.get('sendAttempts') == 1):
            return marker, False
    matches = []
    roots = (sender.STATE_DIR / 'runs', WORKFLOW_RUNS_ROOT)
    seen_paths = set()
    for root in roots:
        pattern = f'**/desktop-wechat/{item["merchantId"]}/receipt.json'
        for receipt_path in root.glob(pattern):
            receipt_path = receipt_path.resolve()
            if receipt_path in seen_paths:
                continue
            seen_paths.add(receipt_path)
            try:
                receipt = json.loads(receipt_path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if _receipt_matches_item(receipt, item, group):
                matches.append(receipt)
    if len(matches) != 1:
        return marker, False
    recovered = matches[0] | {
        'groupName': group,
        'merchantId': item['merchantId'],
        'messageSha256': item['sha256'],
        'payloadType': 'text',
        'payloads': [{'text': item['text'], 'sha256': item['sha256']}],
    }
    sender.atomic_write_json(marker, recovered)
    return marker, True

def execute(args):
    started=time.monotonic();out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=False,mode=0o700)
    result={'ok':False,'runId':str(uuid.uuid4()),'runtimeModelDecisions':0,'stageMs':{},'stageResults':{},'stage':'lock',
            'wechatChannel':args.wechat_channel,'collectionAttempts':[]}
    # One workflow writer per state directory; lock held through final cursor validation.
    lock=open(sender.STATE_DIR/'workflow.lock','a')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        def stage(name,fn):
            result['stage']=name;t=time.monotonic()
            try:
                value=fn();result['stageResults'][name]='PASS';return value
            except Exception:
                result['stageResults'][name]='FAIL';raise
            finally:result['stageMs'][name]=round((time.monotonic()-t)*1000)
        result['executorIntegrity']=stage('executor_integrity',lambda:executor_integrity.verify_for_run(
            args.unsealed_acceptance_authorization))
        result['runtimePolicy']=stage('runtime_policy',lambda:runtime_contract.validate_policy(args,sender))
        result['selftest']=stage('offline_selftest',lambda:runtime_contract.offline_selftest(sender,collector))
        receipt_path=out/'collection.json'
        def collect_bounded():
            collection_started=time.monotonic()
            for attempt in (1,2):
                remaining=180-(time.monotonic()-collection_started)
                if remaining<=0:raise RuntimeError('collection-budget-exceeded')
                attempt_path=out/f'collection-attempt-{attempt}.json'
                value=collector.collect(args.group,sender.cursor_file(args.group),attempt_path,timeout_seconds=remaining)
                summary={k:v for k,v in value.items() if k not in ('messages','cursor')}
                result['collectionAttempts'].append(summary|{'attempt':attempt})
                result['collection']=summary
                collector.private_json(receipt_path,value)
                if value.get('ok') is True:return value
                remaining=180-(time.monotonic()-collection_started)
                if not runtime_contract.may_retry_collection(value,attempt,remaining):
                    raise RuntimeError(value.get('error','collection-failed'))
            raise RuntimeError('collection-attempt-budget-exceeded')
        r=stage('collection',collect_bounded)
        result['collection']={k:v for k,v in r.items() if k not in ['messages','cursor']}
        if not r['ok']:raise RuntimeError(r.get('error','collection-failed'))
        stage('audit',lambda:sender.audit_collection(sender.load_collection(receipt_path,args.group)))
        reconciliation_only = False
        if args.wechat_channel == 'desktop' and r['messages']:
            first = r['messages'][0]
            marker, recovered_marker = recover_unknown_marker_from_receipt(first, args.group)
            previous = json.loads(marker.read_text()) if marker.exists() else None
            if recovered_marker:
                result['recoveredUnknownMarker'] = {'merchantId': first['merchantId'], 'reason': 'private-unknown-receipt-bound'}
            safe_blocked = bool(previous and desktop_wechat_sender.blocked_zero_send_text_marker_matches(
                args.group, first, marker))
            # Any existing non-blocked marker, including a legacy null-attempt
            # unknown receipt, is read-only reconciliation only. Never infer that
            # a missing/unknown count authorizes another send.
            reconciliation_only = bool(previous and not safe_blocked)
            if reconciliation_only:
                result['stageResults']['desktop_wechat_preflight']='SKIPPED'
                result['desktopWechatPreflight']={'ok':True,'skipped':True,'reason':'existing-attempt-reconcile-only','sendAttempts':int(previous.get('sendAttempts') or 0)}
            else:
                result['desktopWechatPreflight']=stage('desktop_wechat_preflight',lambda:desktop_wechat_sender.preflight(
                    args.group,out/'desktop-wechat-preflight',args.wechat_contention_wait_seconds,
                    args.wechat_contention_poll_seconds,pending_item=first))
        elif args.wechat_channel == 'desktop':
            result['stageResults']['desktop_wechat_preflight']='SKIPPED'
            result['desktopWechatPreflight']={'ok':True,'skipped':True,'reason':'no-pending-merchants','sendAttempts':0}
        if args.wechat_channel == 'desktop':
            delivery=stage('desktop_wechat',lambda:desktop_wechat_sender.run(
                receipt_path,args.group,args.standing_authorization,out/'desktop-wechat',
                args.wechat_contention_wait_seconds,args.wechat_contention_poll_seconds,reconciliation_only=reconciliation_only))
        else:
            delivery=stage('phone',lambda:sender.run(SimpleNamespace(group=args.group,serial=args.serial,execute=True,probe_locate_group=False,
                       standing_authorization=args.standing_authorization,collection_receipt=str(receipt_path))))
        collector.private_json(out/'wechat.json',delivery)
        result['wechat']=delivery
        result['wechatChannel']=args.wechat_channel
        if not delivery['ok']:
            result['stageResults'][result['stage']]='FAIL'
            raise RuntimeError(delivery.get('reason','wechat-failed'))
        def check():
            return runtime_contract.audit_final(sender,args.group,r,args.wechat_channel,reconciliation_only=reconciliation_only)
        result['finalCursor']=stage('final_cursor_check',check)
        counts=runtime_contract.delivery_counts(delivery)
        if result['executorIntegrity'].get('status') == 'UNSEALED_ACCEPTANCE' and counts['verifiedNewSends'] > 0:
            result['executorSeal']=stage('reseal',lambda:executor_integrity.seal_from_nonempty_acceptance(result,out))
        else:
            result['stageResults']['reseal']='SKIPPED'
            result['resealReason']=('already-sealed' if result['executorIntegrity'].get('status') == 'SEALED'
                                    else 'real-nonempty-send-required')
        result.update(ok=True,stage='complete')
    except Exception as e:
        result['error']=str(e)
        if result['stage']=='desktop_wechat_preflight' and hasattr(e,'receipt'):
            result['desktopWechatPreflight']=e.receipt
    finally:
        result['elapsedMs']=round((time.monotonic()-started)*1000)
        try:
            result['completion'] = runtime_contract.completion_state(result)
            review=runtime_contract.build_review(result)
            collector.private_json(out/'review.json',review)
            (out/'review.md').write_text(runtime_contract.render_review(review),encoding='utf-8')
            result['reviewPath']=str(out/'review.json')
        except Exception as error:
            result['ok']=False;result['reviewError']=str(error)
        finally:
            collector.private_json(out/'workflow.json',result);lock.close()
    return result
def build_parser():
    p=argparse.ArgumentParser();p.add_argument('--group',default=sender.PRODUCTION_GROUP);p.add_argument('--serial');p.add_argument('--wechat-channel',choices=('mobile','desktop'),default='desktop');p.add_argument('--standing-authorization',required=True);p.add_argument('--output-dir',required=True)
    p.add_argument('--wechat-contention-wait-seconds',type=float,default=desktop_wechat_sender.DEFAULT_CONTENTION_WAIT_SECONDS)
    p.add_argument('--wechat-contention-poll-seconds',type=float,default=desktop_wechat_sender.DEFAULT_CONTENTION_POLL_SECONDS)
    p.add_argument('--unsealed-acceptance-authorization')
    return p


if __name__=='__main__':
    r=execute(build_parser().parse_args());print(json.dumps(r,ensure_ascii=False));raise SystemExit(0 if r['ok'] else 1)

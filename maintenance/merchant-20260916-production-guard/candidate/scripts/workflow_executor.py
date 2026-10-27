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
        if args.unsealed_acceptance_authorization:
            result['executorIntegrity']=stage('executor_integrity',lambda:executor_integrity.verify_unsealed_acceptance(
                args.unsealed_acceptance_authorization))
        else:
            result['executorIntegrity']=stage('executor_integrity',executor_integrity.verify)
        result['runtimePolicy']=stage('runtime_policy',lambda:runtime_contract.validate_policy(args,sender))
        result['selftest']=stage('offline_selftest',lambda:runtime_contract.offline_selftest(sender,collector))
        if args.wechat_channel == 'desktop':
            result['desktopWechatPreflight']=stage('desktop_wechat_preflight',lambda:desktop_wechat_sender.preflight(
                args.group,out/'desktop-wechat-preflight',args.wechat_contention_wait_seconds,args.wechat_contention_poll_seconds))
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
        if args.wechat_channel == 'desktop':
            delivery=stage('desktop_wechat',lambda:desktop_wechat_sender.run(
                receipt_path,args.group,args.standing_authorization,out/'desktop-wechat',
                args.wechat_contention_wait_seconds,args.wechat_contention_poll_seconds))
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
            return runtime_contract.audit_final(sender,args.group,r,args.wechat_channel)
        result['finalCursor']=stage('final_cursor_check',check)
        result.update(ok=True,stage='complete')
    except Exception as e:
        result['error']=str(e)
        if result['stage']=='desktop_wechat_preflight' and hasattr(e,'receipt'):
            result['desktopWechatPreflight']=e.receipt
    finally:
        result['elapsedMs']=round((time.monotonic()-started)*1000)
        try:
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

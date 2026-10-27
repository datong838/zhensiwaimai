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

def execute(args):
    started=time.monotonic();out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True,mode=0o700)
    result={'ok':False,'runId':str(uuid.uuid4()),'runtimeModelDecisions':0,'stageMs':{},'stage':'lock'}
    # One workflow writer per state directory; lock held through final cursor validation.
    lock=open(sender.STATE_DIR/'workflow.lock','a')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        def stage(name,fn):
            result['stage']=name;t=time.monotonic()
            try:return fn()
            finally:result['stageMs'][name]=round((time.monotonic()-t)*1000)
        if args.unsealed_acceptance_authorization:
            result['executorIntegrity']=stage('executor_integrity',lambda:executor_integrity.verify_unsealed_acceptance(
                args.unsealed_acceptance_authorization))
        else:
            result['executorIntegrity']=stage('executor_integrity',executor_integrity.verify)
        if args.wechat_channel == 'desktop':
            result['desktopWechatPreflight']=stage('desktop_wechat_preflight',lambda:desktop_wechat_sender.preflight(
                args.group,out/'desktop-wechat-preflight',args.wechat_contention_wait_seconds,args.wechat_contention_poll_seconds))
        receipt_path=out/'collection.json'
        r=stage('collection',lambda:collector.collect(args.group,sender.cursor_file(args.group),receipt_path))
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
        if not delivery['ok']:raise RuntimeError(delivery.get('reason','wechat-failed'))
        def check():
            current=json.loads(sender.cursor_file(args.group).read_text())
            if r['messages']:
                last=r['messages'][-1]
                if any(current.get(k)!=last[k] for k in ['merchantId','recommendTime','tableOrder']):raise RuntimeError('final-cursor-mismatch')
            if current.get('groupName')!=args.group or current.get('verified') is not True:raise RuntimeError('final-cursor-unverified')
            return {'verified':True,'merchantId':current['merchantId'],'recommendTime':current['recommendTime']}
        result['finalCursor']=stage('final_cursor_check',check)
        result.update(ok=True,stage='complete')
    except Exception as e:result['error']=str(e)
    finally:
        result['elapsedMs']=round((time.monotonic()-started)*1000)
        collector.private_json(out/'workflow.json',result);lock.close()
    return result
def build_parser():
    p=argparse.ArgumentParser();p.add_argument('--group',default=sender.TEST_GROUP);p.add_argument('--serial');p.add_argument('--wechat-channel',choices=('mobile','desktop'),default='desktop');p.add_argument('--standing-authorization',required=True);p.add_argument('--output-dir',required=True)
    p.add_argument('--wechat-contention-wait-seconds',type=float,default=desktop_wechat_sender.DEFAULT_CONTENTION_WAIT_SECONDS)
    p.add_argument('--wechat-contention-poll-seconds',type=float,default=desktop_wechat_sender.DEFAULT_CONTENTION_POLL_SECONDS)
    p.add_argument('--unsealed-acceptance-authorization')
    return p


if __name__=='__main__':
    r=execute(build_parser().parse_args());print(json.dumps(r,ensure_ascii=False));raise SystemExit(0 if r['ok'] else 1)

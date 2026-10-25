#!/usr/bin/env python3
"""One invocation, one attempt. Runtime code owns every continuation gate."""
import argparse,json,subprocess,time,hashlib,re,sys,uuid,importlib.util
from pathlib import Path
from types import SimpleNamespace
import uiautomator2 as u2
import phone_executor as phone
from runtime_guard import (
    CANONICAL_AUTHORIZATION,
    CANONICAL_BROWSER_PORT,
    CANONICAL_BROWSER_PROFILE,
    CANONICAL_TARGET_GROUP,
    CANONICAL_WECHAT_CHANNEL,
    RuntimePolicyError,
    WeChatExecutionGuard,
    validate_runtime_arguments,
    validate_runtime_policy,
)

NODE='/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
ROOT=Path(__file__).resolve().parent
# 2026-10-23 通道切换：全部走本地 Mac 企业微信（WeComAdapter）。workflow_bridge_windows
# 按 registry-routing.json 路由（top10=wecom）；Windows 个人微信网关已废弃，不再使用。
DESKTOP_SENDER=Path('/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/wechat-messaging/scripts/workflow_bridge_windows.py')
DESKTOP_WECHAT=DESKTOP_SENDER.with_name('wechat_desktop.py')
DESKTOP_PREFLIGHT=DESKTOP_SENDER.with_name('workflow_preflight.py')
WINDOWS_WECHAT_SCRIPTS=DESKTOP_SENDER.parent

def windows_wechat_preflight(output_dir):
    """Windows 驱动通道前检：服务就绪 + 目标群可解析（只读，不碰 UI）。"""
    wm_scripts=str(WINDOWS_WECHAT_SCRIPTS)
    if wm_scripts not in sys.path:sys.path.insert(0,wm_scripts)
    from wecom_adapter import WeComAdapter as WindowsAdapter  # 2026-10-23 channel switch → 企微
    adapter=WindowsAdapter()
    return adapter.preflight({'groupName':CANONICAL_TARGET_GROUP,
        'context':{'searchGroupName':None,'deadlineAt':time.time()+120}},output_dir)

def load_shared_preflight():
    spec=importlib.util.spec_from_file_location('top10_wechat_shared_preflight',DESKTOP_PREFLIGHT)
    if spec is None or spec.loader is None:raise phone.StopRun('desktop-wechat-preflight-load-failed')
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module

# `wechat-search-region-contended` is transient compositor contention: the
# shared adapter already waits up to 30s internally per attempt, so the outer
# retry only needs a bounded budget.  An unbounded loop here held the shared
# WeChat interaction lock forever, which starved every later skill in the same
# daemon cycle (the manifest runs top10 first, so nothing after it ever got a
# turn).  The budget is explicit; when it is exhausted the last receipt is
# returned unchanged, keeping the original reason so the scheduler still
# classifies the failure as recoverable, and `contentionExhausted` records why.
MAX_CONTENTION_ATTEMPTS=5
MAX_CONTENTION_SECONDS=150

def run_desktop_preflight_until_ready(preflight_module, group, output_dir, sleep=time.sleep):
    """Recover only code-classified, zero-send transient preflight states."""
    started=time.monotonic()
    attempts=0
    retry_history=[]
    while True:
        attempts+=1
        result=preflight_module.run_exact_group_preflight(group,output_dir/f'attempt-{attempts}')
        if result.get('ok'):
            if retry_history:result['retryHistory']=retry_history
            return result,attempts,round((time.monotonic()-started)*1000)
        retryable=(result.get('reason')=='wechat-search-region-contended'
                   and result.get('sendAttempts')==0
                   and not result.get('hardGate'))
        zero_result_retryable=(result.get('reason')=='exact-group-result-count:0'
                               and result.get('sendAttempts')==0
                               and not result.get('hardGate')
                               and attempts<2)
        if retryable:
            retry_history.append({'reason':result.get('reason'),'waitMs':5000})
            if (attempts>=MAX_CONTENTION_ATTEMPTS
                    or (time.monotonic()-started)>=MAX_CONTENTION_SECONDS):
                result['retryHistory']=retry_history
                result['contentionExhausted']=True
                return result,attempts,round((time.monotonic()-started)*1000)
            sleep(5)
            continue
        if zero_result_retryable:
            retry_history.append({'reason':result.get('reason'),'waitMs':5000})
            sleep(5)
            continue
        if retry_history:result['retryHistory']=retry_history
        return result,attempts,round((time.monotonic()-started)*1000)

def can_retry_cleaned_image_prepare(result):
    """Retry only this run's image preparation after verified zero-send cleanup."""
    return (
        result.get('ok') is not True
        and result.get('reason')=='desktop-image-preview-not-prepared'
        and result.get('payloadType')=='image'
        and result.get('sendAttempts')==0
        and result.get('uncommittedPreviewCleanup')=='attempted'
        and result.get('uncommittedPreviewCleared') is True
        and not result.get('attemptMarker')
        and result.get('state')!='unknown'
    )

def ensure_screen_ready(d,serial):
    if not d.info.get('screenOn'):
        phone.adb(serial,'shell','input','keyevent','KEYCODE_WAKEUP')
        deadline=time.monotonic()+2
        while not d.info.get('screenOn'):
            if time.monotonic()>=deadline:raise phone.StopRun('phone-screen-not-ready')
            time.sleep(.1)
    if d.screenshot().size!=(1080,2340):raise phone.StopRun('phone-screen-not-ready')

def run(args):
    workflow_run_id=str(uuid.uuid4())
    workflow_dir=ROOT.parent/'.runtime'/'workflow-runs'/workflow_run_id
    workflow_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    workflow_receipt=workflow_dir/'workflow_receipt.json'
    transport={}
    serial=transport.get('serial')
    started=time.monotonic()
    result={'ok':False,'executor':'workflow','runId':workflow_run_id,'sendAttempts':0,
            'preflightMs':0,'runtimeModelDecisions':0,'receiptFile':str(workflow_receipt)}
    wechat_guard=None
    try:
        policy=validate_runtime_policy()
        validate_runtime_arguments(args)
        if phone.TARGET_GROUP!=CANONICAL_TARGET_GROUP or phone.AUTHORIZATION!=CANONICAL_AUTHORIZATION:
            raise RuntimePolicyError('runtime-policy-code-constant-mismatch')
        result['runtimePolicy']={
            'policyId':policy['policyId'],
            'browserProfile':policy['browserProfile'],
            'browserPort':policy['browserPort'],
            'wechatChannel':policy['wechatChannel'],
            'validatedFileCount':len(policy['validatedFiles']),
        }
        rehearsal=bool(getattr(args,'rehearse',False))
        if rehearsal and args.execute:raise phone.StopRun('rehearsal-cannot-send')
        repeat_id=getattr(args,'authorized_repeat_id',None)
        if repeat_id is not None:
            if not args.execute or not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}',repeat_id):raise phone.StopRun('invalid-repeat-authorization')
            result['authorizedRepeatId']=repeat_id
        result['mode']='rehearsal-preview-no-send' if rehearsal else ('execute' if args.execute else 'dry-run')
        if args.wechat_channel == 'mobile':
            if not serial or phone.adb(serial,'get-state')!='device':raise phone.StopRun('phone-not-ready')
            device_hash=hashlib.sha256(phone.adb(serial,'shell','getprop','ro.serialno').encode()).hexdigest()[:12]
            if device_hash!='f2724cf436e9' or phone.adb(serial,'shell','getprop','ro.product.model')!='HLK-AL00':raise phone.StopRun('phone-identity-mismatch')
            d=u2.connect(serial); ensure_screen_ready(d,serial); result['deviceHash']=device_hash
        else:
            windows_wechat_preflight_receipt=windows_wechat_preflight(workflow_dir/'windows-wechat-preflight')
            result['windowsWechatPreflight']={k:windows_wechat_preflight_receipt.get(k) for k in ('ok','reason','candidateStrategy','resolvedGroup')}
            if not windows_wechat_preflight_receipt.get('ok'):
                raise phone.StopRun('windows-wechat:'+str(windows_wechat_preflight_receipt.get('reason') or 'preflight-failed'))
        # The shared desktop preflight owns the UI lock itself. Acquire the
        # Top10 lease only after it returns, so the parent cannot self-deadlock.
        wechat_guard=WeChatExecutionGuard(owner=f'top10:{workflow_run_id}')
        result['wechatGuard']=wechat_guard.acquire()
        result['preflightMs']=round((time.monotonic()-started)*1000); result['wechatChannel']=args.wechat_channel
        if not args.execute and not rehearsal:
            result.update(ok=True,mode='dry-run')
            return result
        if args.execute and args.standing_authorization!=phone.AUTHORIZATION:raise phone.StopRun('standing-authorization-missing')
        output=subprocess.run([NODE,str(ROOT/'desktop_background_executor.mjs'),'--profile',CANONICAL_BROWSER_PROFILE,'--port',str(CANONICAL_BROWSER_PORT)],capture_output=True,text=True,timeout=None)
        desktop=json.loads(output.stdout.strip().splitlines()[-1])
        result.update(desktopRunId=desktop['runId'],desktop=desktop)
        if not desktop.get('ok') or output.returncode:raise phone.StopRun('desktop:'+desktop.get('reason','failed'))
        receipt,image=phone.load_receipt(Path(desktop['receiptFile']), enforce_expiry=args.wechat_channel != 'desktop')
        if args.wechat_channel == 'desktop':
            if rehearsal: raise phone.StopRun('desktop-rehearsal-not-supported')
            result['wechatGuard']=wechat_guard.wait_until_quiet()
            # The child sender acquires the same shared UI lock. Release the
            # parent lease before spawning it to avoid self-deadlock.
            result['wechatGuard']=wechat_guard.release()
            wechat_guard=None
            group_key=hashlib.sha256(phone.TARGET_GROUP.encode()).hexdigest()[:12]
            suffix=f'-repeat-{repeat_id}' if repeat_id else ''
            marker=f"{receipt['dataDate']}-main-{group_key}{suffix}.json"
            ledger=ROOT.parent/'.runtime'/'send-ledger'
            cmd=[sys.executable,str(DESKTOP_SENDER), "--workflow-id", "top10",'--group',phone.TARGET_GROUP,'--payload-type','image','--item',str(image),
                 '--authorization',args.standing_authorization,'--ledger',str(ledger),'--marker-name',marker,
                 '--output-dir',str(Path(desktop['receiptFile']).parent/'desktop-wechat'),'--deadline-unix',str(desktop['deadlineAt']/1000),'--execute']
            send_retry_history=[]
            while True:
                sent=subprocess.run(cmd,capture_output=True,text=True,timeout=None)
                try:
                    p=json.loads(sent.stdout.strip().splitlines()[-1])
                except (IndexError, json.JSONDecodeError):
                    p={'ok':False,'reason':'desktop-send-no-receipt','sendAttempts':0}
                if sent.returncode: p['ok']=False
                # A lock timeout is a waiting state, never a terminal result.
                # Retry only before any send attempt; unknown/attempted outcomes
                # remain fail-closed and are never resent.
                if (not p.get('ok') and p.get('reason') in {
                    'wechat-interaction-lock-timeout', 'resource_wait'
                } and p.get('sendAttempts')==0):
                    time.sleep(5)
                    continue
                if not send_retry_history and can_retry_cleaned_image_prepare(p):
                    send_retry_history.append({
                        'reason':p.get('reason'),
                        'sendAttempts':p.get('sendAttempts'),
                        'uncommittedPreviewCleared':p.get('uncommittedPreviewCleared'),
                        'waitMs':1000,
                    })
                    time.sleep(1)
                    continue
                break
            if send_retry_history:p['retryHistory']=send_retry_history
        else:
            ensure_screen_ready(d,serial)
            p=phone.run_executor(SimpleNamespace(desktop_receipt=desktop['receiptFile'],serial=serial,execute=args.execute,train_phone=rehearsal,training_deadline_at=desktop['deadlineAt'],authorized_repeat_id=repeat_id,standing_authorization=args.standing_authorization,group=phone.TARGET_GROUP,instance='main',probe_locate_group=False))
        result.update(delivery=p,sendAttempts=p.get('sendAttempts',0),ok=bool(p.get('ok')))
        result['desktopWechat' if args.wechat_channel=='desktop' else 'phone']=p
        if not p.get('ok'):result['reason']=('desktop-wechat:' if args.wechat_channel=='desktop' else 'mobile-wechat:')+p.get('reason','failed')
        result['endToEndMs']=round(time.time()*1000-desktop['startedAt'])
    except Exception as e:
        result['ok']=False
        result['reason']=str(e)
    finally:
        if wechat_guard is not None:
            result['wechatGuard']=wechat_guard.release()
        result['wallMs']=round((time.monotonic()-started)*1000)
        workflow_receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2));workflow_receipt.chmod(0o600)
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--transport-file');p.add_argument('--wechat-channel',choices=('mobile','desktop'),default='desktop');p.add_argument('--browser-profile',default='taobao-brand');p.add_argument('--browser-port',type=int,default=9230);mode=p.add_mutually_exclusive_group();mode.add_argument('--execute',action='store_true');mode.add_argument('--rehearse',action='store_true');p.add_argument('--standing-authorization');p.add_argument('--authorized-repeat-id');args=p.parse_args()
    if args.wechat_channel=='mobile' and not args.transport_file:p.error('--transport-file is required for mobile channel')
    r=run(args)
    compact={k:v for k,v in r.items() if k not in ['desktop','phone']}
    for part in ['desktop','desktopWechat','phone']:
        if part in r:compact[part]={k:v for k,v in r[part].items() if k in ['ok','stageMs','reason','sendAttempts','elapsedMs','file','width','height','largeImageVerification','runId']}
    print(json.dumps(compact,ensure_ascii=False));raise SystemExit(0 if r.get('ok') else 1)

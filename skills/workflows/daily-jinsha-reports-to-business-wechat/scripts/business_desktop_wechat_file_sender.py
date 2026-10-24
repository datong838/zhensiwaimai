#!/usr/bin/env python3
"""Desktop-WeChat file sender with the business pipeline CLI contract."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from business_wechat_file_sender import AUTHORIZATION, DELIVERY_LEDGER, TARGET_GROUP, load_frozen_sender

# 2026-10-23 通道切换：桌面微信不再给 AI 使用，发送走本地 Mac 企业微信（WeComAdapter）。
DESKTOP = Path('/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/wechat-messaging/scripts/workflow_bridge_windows.py')
DESKTOP_WECHAT = DESKTOP.with_name('wechat_desktop.py')
DESKTOP_PREFLIGHT = DESKTOP.with_name('workflow_preflight.py')
ATTEMPTS = DELIVERY_LEDGER.with_suffix('.desktop-attempts')
INTERNAL_INVOCATION = 'business-workflow-executor-v1'


def json_items(items: list[dict]) -> list[dict]:
    return [{**item, 'file': str(item['file'])} for item in items]


def item_confirmed(ledger: dict, item: dict) -> bool:
    direct = ledger['files'].get(item['sha256'], {})
    if direct.get('state') == 'confirmed':
        return True
    same_name = [value for value in ledger['files'].values()
                 if value.get('name') == item['name'] and value.get('state') == 'confirmed'
                 and value.get('fullNameVerified') is True and value.get('groupTitleVerified') is True]
    return len(same_name) == 1


def _load_shared_preflight():
    spec=importlib.util.spec_from_file_location('business_wechat_shared_preflight',DESKTOP_PREFLIGHT)
    if spec is None or spec.loader is None:raise RuntimeError('desktop-wechat-preflight-load-failed')
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module


def preflight(group: str, output_dir: Path | None = None) -> dict:
    """Windows 驱动通道前检：服务就绪 + 目标群可解析（只读，不碰 UI）。"""
    import sys as _sys
    _wm = str(DESKTOP.parent)
    if _wm not in _sys.path:
        _sys.path.insert(0, _wm)
    from wecom_adapter import WeComAdapter as WindowsAdapter  # 2026-10-23 channel switch → 企微
    receipt = WindowsAdapter().preflight(
        {'groupName': group, 'context': {'searchGroupName': None,
                                         'deadlineAt': time.time() + 120}},
        output_dir or Path('/tmp/jinsha-windows-preflight'))
    if receipt.get('ok') is not True:
        raise RuntimeError('windows-wechat-' + str(receipt.get('reason') or 'preflight-failed'))
    return receipt


def main() -> int:
    if os.environ.get('JINSHA_WORKFLOW_INTERNAL') != INTERNAL_INVOCATION:
        print(json.dumps({'ok':False,'reason':'direct-stage-invocation-forbidden'},ensure_ascii=False));return 1
    p=argparse.ArgumentParser();p.add_argument('--build-receipt',required=True);p.add_argument('--send-receipt',required=True)
    p.add_argument('--group',required=True);p.add_argument('--execute',action='store_true');p.add_argument('--verify-only',action='store_true')
    p.add_argument('--authorization');p.add_argument('--deadline-unix');p.add_argument('--keep-work',action='store_true');args=p.parse_args()
    if args.group!=TARGET_GROUP or (args.execute and args.authorization!=AUTHORIZATION):
        print(json.dumps({'ok':False,'groupName':args.group,'reason':'business-binding-mismatch'},ensure_ascii=False));return 1
    try:desktop_preflight=preflight(args.group,Path(args.send_receipt).resolve().parent/'desktop-wechat-preflight')
    except Exception as error:
        print(json.dumps({'ok':False,'groupName':args.group,'sent':[],'channel':'desktop','reason':str(error)},ensure_ascii=False));return 1
    module=load_frozen_sender();_,loaded_items=module.load_build_receipt(Path(args.build_receipt))
    items=json_items(loaded_items)
    mobile_ledger=module.load_delivery_ledger(DELIVERY_LEDGER)
    already=[item_confirmed(mobile_ledger,item) for item in items]
    if any(already) and not all(already):
        print(json.dumps({'ok':False,'groupName':args.group,'sent':[],'reason':'cross-channel-partial-history'},ensure_ascii=False));return 1
    if all(already):
        result={'ok':True,'groupName':args.group,'sent':items,'channel':'desktop','desktopWechatPreflight':desktop_preflight,'reusedMobileLedger':True}
        Path(args.send_receipt).write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False));return 0
    identity=hashlib.sha256((args.group+'\n'+'\n'.join(item['sha256'] for item in items)).encode()).hexdigest()
    marker=ATTEMPTS/(identity+'.json')
    cmd=[sys.executable,str(DESKTOP),'--workflow-id','jinsha-reports','--group',args.group,
         '--payload-type','file','--authorization',AUTHORIZATION,'--ledger',str(ATTEMPTS),
         '--marker-name',identity+'.json','--output-dir',str(Path(args.send_receipt).resolve().parent/'desktop-wechat'),'--execute']
    if args.deadline_unix:cmd.extend(['--deadline-unix',args.deadline_unix])
    for item in items:cmd.extend(['--item',str(item['file'])])
    from business_wecom_recovery import recover
    recovered=recover(cmd,verify_only=args.verify_only)
    if args.verify_only:
        data=json.loads(marker.read_text()) if marker.exists() else {}
        ok=data.get('verified') is True and [x.get('sha256') for x in data.get('payloads',[])]==[x['sha256'] for x in items]
        result={'ok':ok,'groupName':args.group,'sent':items if ok else [],'channel':'desktop','desktopWechatPreflight':desktop_preflight,'reason':None if ok else 'desktop-verified-receipt-missing'}
        if ok:
            for item in items:
                mobile_ledger['files'][item['sha256']]={'name':item['name'],'size':item['size'],'state':'confirmed',
                    'channel':'desktop','confirmedAt':time.time(),'fullNameVerified':True,'groupTitleVerified':True,
                    'desktopReceipt':str(marker)}
            module.atomic_json(DELIVERY_LEDGER,mobile_ledger)
            result['confirmedBusinessLedgerFromDesktopAttempt']=True
    else:
        out=Path(args.send_receipt).resolve().parent/'desktop-wechat'
        cmd=[sys.executable,str(DESKTOP), "--workflow-id", "jinsha-reports",'--group',args.group,'--payload-type','file','--authorization',args.authorization,
             '--ledger',str(ATTEMPTS),'--marker-name',identity+'.json','--output-dir',str(out),'--execute']
        if args.deadline_unix:cmd.extend(['--deadline-unix',args.deadline_unix])
        for item in items:cmd.extend(['--item',str(item['file'])])
        try:
            proc=subprocess.CompletedProcess(cmd,0 if recovered.get('verified') else 1,json.dumps(recovered),'') if recovered is not None else subprocess.run(cmd,capture_output=True,text=True,timeout=900)
        except subprocess.TimeoutExpired:
            result={'ok':False,'groupName':args.group,'sent':[],'channel':'desktop','desktopWechatPreflight':desktop_preflight,'reason':'desktop-send-timeout'}
            Path(args.send_receipt).write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False));return 1
        raw=json.loads(proc.stdout.strip().splitlines()[-1])
        result={'ok':proc.returncode==0 and raw.get('verified') is True,'groupName':args.group,'sent':items if raw.get('verified') else [],
                'channel':'desktop','desktopWechatPreflight':desktop_preflight,'desktop':raw}
        if not result['ok']:result['reason']=raw.get('reason','desktop-send-failed')
        else:
            for item in items:
                mobile_ledger['files'][item['sha256']]={'name':item['name'],'size':item['size'],'state':'confirmed',
                    'channel':'desktop','confirmedAt':time.time(),'fullNameVerified':True,'groupTitleVerified':True,
                    'desktopReceipt':str(out/'receipt.json')}
            module.atomic_json(DELIVERY_LEDGER,mobile_ledger)
    Path(args.send_receipt).write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False));return 0 if result['ok'] else 1


if __name__=='__main__':raise SystemExit(main())

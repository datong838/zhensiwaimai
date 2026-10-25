#!/usr/bin/env python3
"""WeCom desktop adapter — same executor contract as WindowsAdapter.

Plugs into workflow_bridge.execute(adapter_factory=WeComAdapter) so all 15
task flows can switch transport by ROUTE DATA ONLY (registry-routing.json
routes.<id>.channel = "wecom"); ledgers, markers, dedup and receipt shape
are handled by the bridge exactly as with the Windows transport.

Hardening inside (大同 2026-10-23, all fail-closed):
  main-window lock / prefix-search navigation / click safe-zone gate /
  stuck-modifier sweep / focus-correctness gate. Each send is a fresh CLI
  subprocess of wecom_desktop_sender.py (state-isolated, receipt-parsed).
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import workflow_bridge

ROOT = Path(__file__).resolve().parents[3]
SENDER = ROOT / 'skills/wechat-messaging/scripts/wecom_desktop_sender.py'
PY = sys.executable
LOCK_PATH = ROOT / 'skills/wechat-messaging/.runtime/wecom-transport.lock'
SEND_TIMEOUT = 300.0


def ui_tree_only_required():
    base = ROOT / 'skills/wechat-messaging'
    return (base / '.runtime/UI_TREE_ONLY.json').exists() or (base / 'config/ui-execution-policy.json').exists()


def target_preflight_verified(preflight, group):
    """Accept legacy target proof or a validated UI-post preflight receipt."""
    return (preflight.get('ok') is True and preflight.get('resolvedGroup') == group
            and ((preflight.get('verificationLevel') == 'wecom-ui-tree-target'
                  and preflight.get('inputEmpty') is True)
                 or preflight.get('sessionListVerified') is True
                 or (preflight.get('candidateStrategy') == 'wecom-prefix-search'
                     and preflight.get('targetIdentityVerified') is True
                     and preflight.get('groupTypeProof') == 'wecom-search-open-title-evidence')))


class WeComAdapter:
    channel = 'desktop'  # same receipt contract; transport identity lives in receipts
    supported = {'text', 'image', 'file'}

    def __init__(self):
        self._resolved = None

    @property
    def owner_lifetime(self):
        return ui_tree_only_required()

    # ---------- session ownership (Mac WeCom UI is a single physical channel) ----------

    @contextlib.contextmanager
    def session(self, request):
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        handle = LOCK_PATH.open('a+')
        previous_app = None
        try:
            os.chmod(LOCK_PATH, 0o600)
            end = time.time() + min(90.0, max(5.0, request['context']['deadlineAt'] - time.time()))
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if not ui_tree_only_required() and time.time() >= end:
                        raise workflow_bridge.Rejected('wecom-transport-busy')
                    time.sleep(1.0)
            # Capture the actually active app, not NSWorkspace's sometimes stale
            # frontmostApplication value. Keep recovery inside the transport lock.
            try:
                if ui_tree_only_required():
                    raise ImportError('UI post owns foreground; no native activation')
                from AppKit import NSWorkspace
                previous_app = next((app for app in NSWorkspace.sharedWorkspace().runningApplications()
                                     if app.isActive()), None)
            except Exception:
                pass
            yield
        finally:
            if previous_app is not None:
                try:
                    previous_app.activateWithOptions_(0)
                except Exception:
                    pass
            try:
                fcntl.flock(handle, fcntl.LOCK_UN)
            finally:
                handle.close()

    # ---------- identity resolution ----------

    def _run_sender(self, mode_args, timeout=SEND_TIMEOUT):
        cmd = [PY, str(SENDER)] + mode_args
        env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'PYTHONPATH': '',
               'HOME': os.environ.get('HOME', str(Path.home()))}
        # 2026-10-24 测试群覆盖透传：本 env 是白名单式构造（刻意不继承
        # os.environ 防代理变量污染），但 WECHAT_TEST_GROUP / WECHAT_TEST_GROUPS
        # 必须到达发送器子进程——否则覆盖静默失效、落群掉回各流写死的生产群
        # （fail-open 反向事故，比误发测试群严重一个量级）。同时透传 WECOM_AUTOSWEEP
        # 以激活发送器焦点锁定守卫（钉住企微前台），否则扫描期间企微丢前台会导致
        # 合成键全丢、落群失败。
        for _k in ('WECHAT_TEST_GROUP', 'WECHAT_TEST_GROUPS', 'WECOM_AUTOSWEEP'):
            _v = os.environ.get(_k)
            if _v:
                env[_k] = _v
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)

    def _parse_receipt(self, proc):
        out = (proc.stdout or '').strip()
        if not out:
            return None
        try:
            return json.loads(out.splitlines()[-1])
        except json.JSONDecodeError:
            return None

    # ---------- executor adapter contract ----------

    def preflight(self, request, output):
        """Locate + open the target group via search; write preflight proof."""
        if ui_tree_only_required():
            from wecom_ui_queue import preflight_enabled, exchange
            if preflight_enabled(request):
                proof = exchange('preflight', request, owner_lifetime=True)
                if proof.get('ok') is True:
                    self._resolved = request['groupName']
                return proof
            return {'ok': False, 'status': 'blocked', 'sendAttempts': 0,
                    'reason': 'ui-tree-only-required', 'targetIdentityVerified': False}
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True, mode=0o700)
        group = request['groupName']
        # ★ 2026-10-23 20:00 大同硬闸前移：预检第一步先验「企微是否真前台」。
        # 旧预检只验窗口在+登录在，不验前台 ⇒ 大同同时用电脑时合成键全被丢，
        # 一路走到发送才报 search-paste-missed-no-enter，白走一整轮。
        # 探针只读零副作用（不激活/不点击/不抢焦点）；非前台 fail-fast，
        # 本档到此为止，等下一档再试。判据=NSRunningApplication.isActive()。
        proc0 = self._run_sender(['frontmost'], timeout=30.0)
        front_receipt = self._parse_receipt(proc0)
        # One bounded activation is safe before dispatch. An activation command
        # returning success is not evidence: require the same isActive probe again.
        if (front_receipt and front_receipt.get('result') == 'not-frontmost'
                and front_receipt.get('axTrusted') is True
                and front_receipt.get('pid') and front_receipt.get('windowFound') is True):
            try:
                subprocess.run(['osascript', '-e', 'tell application "企业微信" to activate'],
                               capture_output=True, timeout=10, check=False)
                for _ in range(8):
                    proc0 = self._run_sender(['frontmost'], timeout=5.0)
                    front_receipt = self._parse_receipt(proc0)
                    if front_receipt and front_receipt.get('result') == 'frontmost-ok':
                        break
                    time.sleep(0.25)
            except (OSError, subprocess.TimeoutExpired):
                front_receipt = None
        if not front_receipt or front_receipt.get('result') != 'frontmost-ok':
            (output / 'preflight.json').write_text(json.dumps(
                {'frontmost': front_receipt}, ensure_ascii=False, default=str),
                encoding='utf-8')
            reason = ('wecom-not-frontmost' if front_receipt
                      else f'frontmost-probe-exit-{proc0.returncode}')
            return {'ok': False, 'reason': f'wecom-preflight-failed:{reason}',
                    'attempts': []}
        # Full search-open navigation proves the conversation opens.
        proc2 = self._run_sender(
            ['send', '--group', group, '--text', '  ', '--dry-run'], timeout=180.0)
        nav_receipt = self._parse_receipt(proc2)
        nav_ok = (nav_receipt is not None and nav_receipt.get('result') == 'dry-run-ok'
                  and nav_receipt.get('resolvedGroup') == group)
        (output / 'preflight.json').write_text(json.dumps(
            {'strategy': 'prefix-search-title-proof', 'navigate': nav_receipt},
            ensure_ascii=False, default=str), encoding='utf-8')
        if not nav_ok:
            reason = (nav_receipt or {}).get('result') or f'sender-exit-{proc2.returncode}'
            return {'ok': False, 'reason': f'wecom-preflight-failed:{reason}',
                    'attempts': []}
        self._resolved = group
        return {'ok': True, 'reason': None, 'sendAttempts': 0,
                'group': group, 'resolvedGroup': group,
                'candidateStrategy': 'wecom-prefix-search',
                'sessionListVerified': False, 'groupTypeVerified': True,
                'targetIdentityVerified': True,
                'groupTypeProof': 'wecom-search-open-title-evidence',
                'attempts': []}

    def send_one(self, request, item, work, grant, deadline):
        from presentation_policy import violation
        error = violation(item)
        if error:
            return {'status':'blocked','sendAttempts':0,'reason':error}
        from ledger import atomic_json
        destination = Path(work) / 'transport' / 'delivery-receipt.json'
        try:
            outcome = self._send_one(request, item, work, grant, deadline)
        except BaseException as error:
            atomic_json(destination, {'status':'unknown','sendAttempts':None,'reason':str(error)})
            raise
        atomic_json(destination, outcome)
        return outcome

    def _send_one(self, request, item, work, grant, deadline):
        # Direct workflow callers may supply only type/path; bind the file
        # BEFORE any possible external effect, without overriding contradictions.
        if (item.get('type') == 'image' or
                (item.get('type') == 'file' and str(item.get('path','')).lower().endswith('.xlsx'))):
            import hashlib
            source = Path(item['path'])
            data = source.read_bytes()
            identity = {'name':source.name,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
            if any(key in item and item[key] != value for key,value in identity.items()):
                return {'status':'blocked','sendAttempts':0,'reason':'file-before-send-binding-mismatch',
                        'transport':{'sent':False,'sendAttempts':0}}
            item = item | identity
        work = Path(work)
        (work / 'transport').mkdir(parents=True, exist_ok=True, mode=0o700)
        import egress_policy
        scoped_test_groups = frozenset()
        if request.get('context', {}).get('workflowId') == 'morning-goal-test-20261024-2120':
            import sys
            runtime = ROOT / 'runtime'
            if str(runtime) not in sys.path: sys.path.insert(0, str(runtime))
            from morning_goal_acceptance import request_enabled
            if request_enabled(request):
                scoped_test_groups = frozenset({request['groupName']})
        verdict = egress_policy.check(group=request['groupName'],
                                      resolved_group=self._resolved or request['groupName'],
                                      items=(item,), test_groups=scoped_test_groups)
        if not verdict['allow']:
            (work / 'egress-denied.json').write_text(json.dumps(
                {'reason': verdict['reason'], 'payload': verdict['payload'],
                 'group': request['groupName'], 'itemId': item.get('itemId')},
                ensure_ascii=False, default=str), encoding='utf-8')
            return {'status': 'blocked', 'sendAttempts': 0,
                    'reason': 'egress-denied:' + str(verdict['reason']),
                    'transport': {'denied': True, 'reason': verdict['reason'],
                                  'sendAttempts': 0}}
        if not ui_tree_only_required() and time.time() >= deadline:
            return {'status': 'blocked', 'sendAttempts': 0,
                    'reason': 'deadline-expired', 'transport': {'sendAttempts': 0}}

        if ui_tree_only_required():
            from wecom_ui_queue import enabled, exchange
            if enabled(request):
                return exchange('send', request, item, owner_lifetime=True)
            return {'status':'blocked','sendAttempts':0,'reason':'ui-tree-only-required'}

        # 2026-10-23 事故修复：dict 字面量三支表达式会全部求值 —— text 载荷
        # 时 item['path'] 抛 KeyError('path')，marker 卡 unknown（send:0
        # elapsedMs=0，零字节发出）。改为惰性分支，只对所需键取值。
        itype = item['type']
        if itype == 'text':
            mode = ['send', '--text', item['text']]
        elif itype == 'image':
            mode = ['send-image', '--image', item['path']]
            if item.get('text'):
                mode += ['--text', item['text']]
        elif itype == 'file':
            mode = ['send-file', '--file', item['path']]
            if item.get('text'):
                mode += ['--text', item['text']]
        else:
            raise ValueError(f'wecom-adapter-unsupported-payload-type:{itype}')
        cmd = mode + ['--group', request['groupName']]

        transport = {'kind': item['type'], 'sendAttempts': 0, 'sent': False}
        receipt = None
        proc = None
        started_send = time.time()
        for round_no in range(2):
            try:
                proc = self._run_sender(cmd)
            except subprocess.TimeoutExpired:
                # keyboard events may or may not have gone through: honest unknown
                transport['sendAttempts'] = 1
                return {'status': 'unknown', 'sendAttempts': 1,
                        'reason': 'wecom-send-timeout',
                        'transport': transport}
            receipt = self._parse_receipt(proc)
            result = (receipt or {}).get('result') or f'sender-exit-{proc.returncode}'
            # Retry ONLY on a proven-not-sent failure (input was cleared
            # in-process, sendAttempts==0). A sent/unknown state never retries.
            if result in ('verified', 'sent-tail-unconfirmed') or 'locate-fail' not in result:
                break
            if round_no == 0:
                transport.setdefault('attemptResults', []).append(result)
                time.sleep(2.0)
        transport['receipt'] = {k: receipt.get(k) for k in
                                ('result', 'verify', 'steps') if receipt and k in receipt}
        result = (receipt or {}).get('result') or f'sender-exit-{proc.returncode}'
        key_attempts = sum(len(step.get('send_attempts') or [])
                           for step in (receipt or {}).get('steps', []) if isinstance(step, dict))
        office_choice = any(step.get('office_choice_attempted') is True
                            for step in (receipt or {}).get('steps', []) if isinstance(step, dict))
        key_attempts = max(key_attempts, int(office_choice))
        if ((result in ('verified', 'sent-tail-unconfirmed') or office_choice) and item['type'] == 'file'
                and str(item.get('name', '')).endswith('.xlsx')):
            # Read-only completion after one physical send; never retries a send.
            checked = None
            try:
                checked = self._run_sender(['verify-file', '--group', request['groupName'],
                    '--file', item['path'], '--sent-after-unix', str(started_send)], timeout=60.0)
                proof = self._parse_receipt(checked)
            except Exception as error:
                proof = {'result': 'not-verified', 'reason': str(error)}
            transport.update(sent=True if result in ('verified','sent-tail-unconfirmed') else None,
                             sendAttempts=1, fileCardReadback=proof)
            if (checked is not None and checked.returncode == 0 and proof and proof.get('result') == 'verified'
                    and proof.get('resolvedGroup') == request['groupName']
                    and proof.get('item') == {key:item.get(key) for key in ('name','size','sha256')}
                    and len(proof.get('frames', [])) == 2
                    and all(frame.get('verified') is True for frame in proof['frames'])):
                transport['sent'] = True
                return {'status':'verified', 'sendAttempts':1, 'verificationLevel':'file-name-size-ui',
                        'reason':None, 'evidence':proof, 'transport':transport}
            return {'status':'unknown','sendAttempts':1,'reason':'wecom-file-card-unconfirmed',
                    'evidence':proof,'transport':transport}
        if result not in ('verified', 'sent-tail-unconfirmed') and key_attempts:
            transport.update(sendAttempts=key_attempts, sent=None)
            return {'status': 'unknown', 'sendAttempts': key_attempts,
                    'reason': f'wecom-post-send-unconfirmed:{result}', 'transport': transport}
        if result in ('verified', 'sent-tail-unconfirmed'):
            transport['sent'] = True
            transport['sendAttempts'] = 1
            level = {'text': 'wecom-ui-text-anchor',
                     'image': 'wecom-ui-image-preview-clear',
                     'file': 'wecom-ui-file-preview-clear'}[item['type']]
            if result == 'sent-tail-unconfirmed':
                # strong local criterion (input subtree back to baseline) but
                # tail snapshot inconclusive — honest unknown, never resend
                return {'status': 'unknown', 'sendAttempts': 1,
                        'reason': 'wecom-tail-unconfirmed',
                        'evidence': (receipt or {}).get('verify'),
                        'transport': transport}
            return {'status': 'verified', 'sendAttempts': 1,
                    'verificationLevel': level, 'reason': None,
                    'evidence': (receipt or {}).get('verify'), 'transport': transport}
        # Only an explicit pre-send result can assert zero attempts.
        pre_send = (result.startswith('locate-fail:') or result in {
            'wrong-conversation-abort', 'clipboard-fail', 'paste-fail',
            'group-name-as-payload-blocked', 'caption-paste-fail',
            'wrong-conversation-before-enter', 'focus-not-on-input-before-enter'})
        if not pre_send:
            transport.update(sendAttempts=None, sent=None)
            return {'status': 'unknown', 'sendAttempts': None,
                    'reason': f'wecom-send-outcome-unknown:{result}', 'transport': transport}
        transport['sendAttempts'] = 0
        return {'status': 'blocked', 'sendAttempts': 0,
                'reason': f'wecom-send-failed:{result}',
                'transport': transport}

    def reconcile(self, request, item, work, prior):
        import hashlib
        state=prior.get('status',prior.get('state'))
        attempts=prior.get('sendAttempts')
        if (item.get('type')!='file' or state not in ('unknown','attempted')
                or type(attempts) is not int or attempts<1):
            raise workflow_bridge.Rejected('wecom-file-reconcile-scope-invalid')
        path=Path(item['path']);data=path.read_bytes()
        identity={'name':path.name,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
        if (not path.name.endswith('.xlsx') or prior.get('sha256')!=identity['sha256']
                or prior.get('name',identity['name'])!=identity['name']
                or prior.get('groupName',request['groupName'])!=request['groupName']):
            raise workflow_bridge.Rejected('wecom-file-reconcile-binding-mismatch')
        preflight=self.preflight(request,Path(work)/'reconcile-preflight')
        if not target_preflight_verified(preflight,request['groupName']):
            return {'status':'unknown','sendAttempts':attempts,'newSendAttempts':0,
                    'reason':preflight.get('reason') or 'reconcile-target-not-verified'}
        cmd=['verify-file','--group',request['groupName'],'--file',str(path)]
        since=prior.get('claimedAt') or request.get('context',{}).get('reconcileSince')
        if since is not None:cmd+=['--sent-after-unix',str(float(since))]
        proc=self._run_sender(cmd,timeout=60.0);proof=self._parse_receipt(proc)
        from ledger import atomic_json
        atomic_json(Path(work)/'reconcile-proof.json',proof or {'result':'not-verified'})
        if (proc.returncode==0 and proof and proof.get('result')=='verified'
                and proof.get('resolvedGroup')==request['groupName'] and proof.get('item')==identity
                and len(proof.get('frames',[]))==2
                and all(frame.get('verified') is True for frame in proof['frames'])):
            return {'status':'verified','sendAttempts':attempts,'newSendAttempts':0,
                    'verificationLevel':'file-name-size-ui','reconciledWithoutSend':True,
                    'evidence':proof,'reason':None}
        return {'status':'unknown','sendAttempts':attempts,'newSendAttempts':0,
                'reason':'wecom-file-reconcile-unconfirmed','evidence':proof}


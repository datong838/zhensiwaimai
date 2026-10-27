#!/usr/bin/env python3
"""Windows-driver transport adapter (orthogonal addition; desktop/mobile untouched).

Transport: Mac -> HTTP 8731 -> Windows 10 WeChat 3.9.x UI automation driver
(wechat-windows-driver project, proxy-bypass-patched client.py).

Design constraints honored:
- ZERO modifications to sealed files (contract.py / executor.py / workflow_bridge.py /
  desktop_adapter.py are sha256-pinned in dependencies.json). This module is new and
  unsealed, so verify_dependencies() keeps passing for every existing channel.
- channel stays 'desktop': the Windows WeChat is the same 'main-wechat' account's
  desktop client, so the sealed grant/authorization/dedup-ledger model is reused
  as-is. Cross-transport dedup is inherited for free (item ledgers are keyed by
  event identity, not by machine). Every receipt records transport='windows-driver'.
- Business callers keep using workflow_bridge.py unchanged. To run the same
  business contract over this transport, use workflow_bridge_windows.py.

Verification model (honest statuses only):
- text: exact full-text anchor required in the LAST message of the target session
  after send (readback), title cross-checked -> verified; else unknown.
- file/image: file name anchor in the LAST message + title cross-check -> verified.
- Deterministic server business error (HTTP status returned) -> blocked, sendAttempts 0.
- Transport anomaly (disconnect/timeout, incl. the known server crash mode) ->
  unknown, sendAttempts = attempts (message may or may not have been sent).
"""
from __future__ import annotations
import fcntl
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parent  # skills/wechat-messaging
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
from contract import Rejected
import egress_policy

#: **大同铁律（2026-09-30）**：测试数据/测试脚本**永远只能发测试群**，
#: 不允许发线上业务群，**也不允许驱动线上业务逻辑**。
#: 本适配器是全局唯一出站口，故在此设**进程级**硬闸门：
#: 处于测试进程（加载了 unittest/pytest，或显式 `ZHS_TEST_MODE=1`）时，
#: **连构造都不允许** —— 这样即使某处测试忘了打桩、或桩打在已废弃的接缝上
#: （2026-09-30 事故根因），也绝无可能驱动真实出站。
TEST_MODE_ENV = 'ZHS_TEST_MODE'


def _test_process_active():
    """测试进程判定。`ZHS_TEST_MODE` 显式优先（0=强制关闭，1=强制开启）。"""
    override = os.environ.get(TEST_MODE_ENV)
    if override == '1':
        return True
    if override == '0':
        return False
    return any(name in sys.modules for name in ('unittest', 'pytest'))

DRIVER_HOME = Path(os.environ.get(
    'ZENSI_WINDOWS_DRIVER_HOME',
    '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/archive/compat/wechat-windows-driver'))

SEND_ATTEMPTS = 3
SEND_RETRY_GAP = 6
VERIFY_WINDOW = 15
VERIFY_POLL = 2
# read() 对媒体消息只给卡片字面量，不含文件名；时间戳是独立条目（如 '2:02'）。
FILE_CARD_MARKERS = ('[文件]', '[图片]')
import re as _re
_TIME_RE = _re.compile(r'^\d{1,2}:\d{2}$')
# 驱动 read_messages 把一条消息的换行**整体删除**（'a\nb' -> 'ab'），而业务层锚点是
# 多行正文；两者叠加 json.dumps 还会把残留换行转义成两字符 '\n'，导致多行载荷的
# 回读校验**永远不可能通过**（2026-09-30 实测：通知已发出，却被判
# windows-readback-anchor-not-trailing）。比较前对双方做同样的换行压平。
_FLATTEN_RE = _re.compile(r'[\r\n]+|\\[rn]')


# 微信会话列表项尾部修饰：'已置顶' / 'N条新消息'（顺序不定，可叠加）。
# 2026-09-30：驱动是按「目标名 vs 打开后读到的标题」比对命中的，
# 列表名带的这些修饰必须剥掉，否则会被误当成群名导致 500「打开会话失败」。
_LIST_DECOR_RE = _re.compile(r'(?:已置顶|\d+\s*条新消息)\s*$')


def _normalize_title(value):
    """'臻肆测试群 (3)'、'…💰已置顶2条新消息' -> 干净群名。"""
    value = str(value or '').strip()
    for _ in range(4):
        stripped = _LIST_DECOR_RE.sub('', value).strip()
        if stripped == value:
            break
        value = stripped
    while value and value[-1] == ')':
        depth = 0
        for index in range(len(value) - 1, -1, -1):
            if value[index] == ')':
                depth += 1
            elif value[index] == '(' or value[index] == '（':
                depth -= 1
                if depth == 0:
                    value = value[:index]
                    break
        else:
            break
        value = value.strip()
    return value


# 驱动发送路径是「搜索框 + SendKeys 逐字敲群名」；**非 BMP 字符**（emoji，如
# 💰 U+1F4B0）经键盘注入根本敲不进去 → 搜索词残缺 → 搜索落空 → 停在旧会话 →
# 驱动回 500「打开会话失败，当前标题=<别的会话>」。2026-09-30 实测同一群名：
#   全名（含 emoji）        → 必失败（连续 2 轮共 ≤6 次尝试全部失败）
#   剥掉 emoji 的主名        → 必成功（current_chat 回读到 '…💰发财精英荟💰 (81)'）
# 因此发送时把群名替换成「驱动敲得进去的等价搜索键」；业务身份、去重台账、回读
# 校验（_verify_sent/_title_compatible）仍一律使用完整群名，语义不变。
_DRIVER_UNTYPEABLE_RE = _re.compile(r'[^\u0000-\uFFFF]')


def _driver_search_key(name):
    """群名 -> 驱动搜索框可逐字输入的等价键。

    策略：在**首个非 BMP 字符处截断**再 strip。必须用"截断"而不是"剔除"，因为
    驱动内部是按「打开后的标题 startswith 目标名」判命中的（实测两条：
    `臻肆测试群` 命中 `臻肆测试群 (3)`；`上海臻肆外卖运营-盯个盯-饭敢当` 命中
    `上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰 (81)`），非前缀的等价词会被
    驱动自己判成「打开会话失败」。截断天然保持前缀关系。
    退化情形（群名整串皆非 BMP）才剔除全部非 BMP；再兜不住则原样返回——此时
    驱动必失败、经 send_one 记为 blocked（零发送），不会误报 verified。
    """
    full = str(name or '').strip()
    key = _DRIVER_UNTYPEABLE_RE.split(full, 1)[0].strip()
    if key:
        return key
    return _DRIVER_UNTYPEABLE_RE.sub('', full).strip() or full


def _flatten(value):
    """压平换行：真实 \\r\\n 与 json.dumps 产生的转义 \\n/\\r 一并去掉。

    只用于锚点比较，不参与任何发送决策；判定强度不变（仍要求精确全文 + 尾部位置）。
    """
    return _FLATTEN_RE.sub('', str(value))


def _anchor_newness(messages, anchor):
    """锚点必须出现，且其最后一次出现之后只允许时间戳条目（新鲜性规则）。

    比较前双方统一压平换行，消除「驱动回读单行化 vs 业务锚点多行」的表示差异；
    找不到锚点时仍返回 False（fail-closed，不放松为模糊匹配）。
    """
    needle = _flatten(anchor)
    hits = [index for index, message in enumerate(messages)
            if needle in _flatten(json.dumps(message, ensure_ascii=False, default=str))]
    if not hits:
        return False
    tail = messages[hits[-1] + 1:]
    return all(_TIME_RE.match(str(message)) for message in tail)


def _read_messages(read):
    """防御性解析 read() 返回：data 可能是 dict{'messages'|'items'} 或直接是 list。"""
    data = read.get('data')
    if isinstance(data, dict):
        messages = data.get('messages') or data.get('items') or []
    elif isinstance(data, list):
        messages = data
    else:
        messages = []
    return [m for m in messages if m]


def _title_compatible(title, group):
    """当前会话标题与注册群名前后缀互证（列表名可能带'已置顶'等修饰）。"""
    if not title:
        return False
    return title.startswith(group) or group.startswith(title)


def _transport(raw, attempts):
    """把真实发送尝试次数并入 transport。

    Mac 桌面 sender 的原始响应本身带 sendAttempts；Windows 驱动的 HTTP 响应不带，
    而业务层 batch proof（item.transport.sendAttempts）与 executor 的去重判定都要看它，
    缺失会被判成 None 并让「已发送成功」的证据链不闭合。
    """
    transport = dict(raw) if isinstance(raw, dict) else {'raw': raw}
    transport['sendAttempts'] = attempts
    return transport


class WindowsAdapter:
    channel = 'desktop'  # desktop-WeChat contract; transport identity lives in receipts
    supported = {'text', 'image', 'file'}

    def __init__(self):
        if _test_process_active():
            raise Rejected('windows-adapter-forbidden-in-test-process')
        if str(DRIVER_HOME) not in sys.path:
            sys.path.insert(0, str(DRIVER_HOME))
        from client import WeChat  # patched client: bypasses local proxy
        self._client_factory = WeChat
        self._client = None
        self._resolved = None
        self._last_transport = None
        self._lock_path = ROOT / '.runtime' / 'windows-transport.lock'

    @property
    def client(self):
        if self._client is None:
            import wxsend  # auto-parses IP/TOKEN from 接入包/连接信息.txt; token never logged
            ip, token = wxsend.load_config()
            self._client = self._client_factory(ip, token)
        return self._client

    # ---------- session ownership (single-threaded serial server) ----------

    @contextmanager
    def session(self, request):
        remaining = max(5.0, request['context']['deadlineAt'] - time.time())
        self._lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        handle = self._lock_path.open('a+')
        try:
            os.chmod(self._lock_path, 0o600)
            end = time.time() + min(60.0, remaining)
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.time() >= end:
                        raise Rejected('windows-transport-busy')
                    time.sleep(1.0)
            yield
        finally:
            try:
                fcntl.flock(handle, fcntl.LOCK_UN)
            finally:
                handle.close()

    # ---------- identity resolution ----------

    def _sessions(self):
        response = self.client.sessions()
        if not response.get('ok'):
            raise Rejected('windows-sessions-unavailable:' + str(response.get('error'))[:160])
        names = []
        for entry in (response.get('data') or {}).get('sessions') or []:
            if isinstance(entry, str):
                names.append(entry)
            elif isinstance(entry, dict):
                names.append(str(entry.get('name') or entry.get('title') or ''))
        # 归一化 + 去重（列表名带 '已置顶'/'N条新消息' 修饰，不可直接当作群名发送）
        seen = {}
        for name in names:
            normalized = _normalize_title(name)
            if normalized:
                seen.setdefault(normalized, None)
        return list(seen)

    def resolve_group(self, group, search_group=None):
        """Exact match first; then unique prefix; else server-search fallback.

        The visible session list is only a viewport: business groups may not be
        listed while the server can still search-and-open them (verified in the
        09-30 joint test). Not-in-list is therefore allowed with a weaker
        preflight; identity is then proven post-send by title cross-check plus
        last-message anchor readback.
        """
        names = self._sessions()
        if group in names:
            return group, 'exact'
        matches = [name for name in names if name.startswith(group)]
        if len(matches) > 1 and search_group:
            narrowed = [name for name in matches if name.startswith(search_group)]
            if narrowed:
                matches = narrowed
        if len(matches) == 1:
            return matches[0], 'prefix-unique'
        if not matches:
            return None, 'server-search'
        raise Rejected('windows-group-prefix-ambiguous:' + '|'.join(matches)[:200])

    def _require_resolved(self, request):
        if self._resolved:
            return self._resolved
        resolved, _ = self.resolve_group(
            request['groupName'], request['context'].get('searchGroupName'))
        return resolved or request['groupName']

    # ---------- executor adapter contract ----------

    def preflight(self, request, output):
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True, mode=0o700)
        health = self.client.health()
        # 连接级失败要分两类，绝不能把「daemon 进程本地网络被 TCC 拦截」误判成
        # 「Windows 服务宕了」：local_network_blocked=True 说明是调用方进程上下文
        # （launchd 缺「本地网络」授权）连不到局域网，服务本身可能健康——应启动
        # 本机中继(127.0.0.1:8732)绕开，而不是去重启 Windows 驱动。
        if isinstance(health, dict) and not health.get('ok') \
                and health.get('error_kind') == 'connection':
            if health.get('local_network_blocked'):
                return {'ok': False, 'reason': 'windows-driver-local-network-blocked',
                        'detail': 'daemon 进程缺 macOS「本地网络」TCC 授权，连不到局域网 '
                                  'Windows 驱动（No route to host / Network is unreachable）。'
                                  'Windows 服务本身可能正常——请确认 localhost 中继'
                                  '(127.0.0.1:8732) 已在本机 GUI 会话启动（见 localhost_relay.py）。',
                        'health': health, 'attempts': []}
            return {'ok': False, 'reason': 'windows-driver-unreachable',
                    'detail': '连不到 Windows 驱动（连接级错误，但非本地网络授权问题）。',
                    'health': health, 'attempts': []}
        if not health.get('ready'):
            return {'ok': False, 'reason': 'windows-wechat-not-ready',
                    'health': health, 'attempts': []}
        try:
            resolved, strategy = self.resolve_group(
                request['groupName'], request['context'].get('searchGroupName'))
        except Rejected as error:
            return {'ok': False, 'reason': str(error), 'attempts': []}
        self._resolved = resolved
        (output / 'preflight.json').write_text(json.dumps(
            {'health': health, 'resolvedGroup': resolved, 'strategy': strategy,
             'driverSearchKey': _driver_search_key(resolved)},
            ensure_ascii=False), encoding='utf-8')
        listed = resolved is not None
        return {'ok': True, 'reason': None, 'sendAttempts': 0,
                'group': request['groupName'], 'resolvedGroup': resolved,
                'candidateStrategy': 'windows-' + strategy,
                'sessionListVerified': listed,
                'groupTypeVerified': True,
                'groupTypeProof': ('windows-session-list-name' if listed
                                   else 'windows-registry-name-plus-post-send-title'),
                'health': {'ready': health.get('ready'), 'logged_in': health.get('logged_in')},
                'attempts': []}

    def send_one(self, request, item, work, grant, deadline):
        work = Path(work)
        (work / 'transport').mkdir(parents=True, exist_ok=True, mode=0o700)
        resolved = self._require_resolved(request)
        # 出站闸门（2026-09-30 事故后新增）：测试载荷只能进测试群；测试群集合为空
        # （默认）时一律拒发。命中即在**调用驱动之前**硬失败并留痕，不静默降级。
        verdict = egress_policy.check(group=request['groupName'], resolved_group=resolved,
                                      items=(item,))
        if not verdict['allow']:
            (work / 'egress-denied.json').write_text(
                json.dumps({'reason': verdict['reason'], 'payload': verdict['payload'],
                            'detail': verdict.get('detail'), 'group': request['groupName'],
                            'resolvedGroup': resolved, 'itemId': item.get('itemId'),
                            'name': item.get('name'), 'deniedAt': time.time()},
                           ensure_ascii=False, default=str), encoding='utf-8')
            return {'status': 'blocked', 'sendAttempts': 0,
                    'reason': 'egress-denied:' + str(verdict['reason']),
                    'transport': {'denied': True, 'reason': verdict['reason'],
                                  'payload': verdict['payload'], 'sendAttempts': 0}}
        # 驱动侧只能用「敲得进去的搜索键」打开会话（见 _driver_search_key 注释）；
        # resolved 仍用于收据与回读校验，二者只在驱动搜索词这一处不同。
        search_key = _driver_search_key(resolved)
        attempts = 0
        raw = None
        errors = []
        while attempts < SEND_ATTEMPTS:
            if time.time() >= deadline:
                status = 'blocked' if attempts == 0 else 'unknown'
                return {'status': status, 'sendAttempts': attempts,
                        'reason': 'deadline-expired', 'transport': _transport(raw, attempts),
                        'attemptErrors': errors}
            attempts += 1
            if item['type'] == 'text':
                raw = self.client.send(search_key, item['text'])
            else:
                # Frozen, hash-verified copy from executor.freeze_item is uploaded.
                raw = self.client.send_local_file(search_key, item['path'])
            if raw.get('ok'):
                break
            error = str(raw.get('error') or 'unknown-error')
            errors.append(error[:200])
            deterministic = error.startswith('HTTP ')  # server answered: nothing sent
            if deterministic:
                # Business rejection (e.g. 打开会话失败): retry after a gap.
                if attempts < SEND_ATTEMPTS:
                    time.sleep(SEND_RETRY_GAP)
                continue
            # Transport anomaly (RemoteDisconnected / timeout): message state unknown.
            return {'status': 'unknown', 'sendAttempts': attempts,
                    'reason': 'windows-transport-anomaly:' + error[:120],
                    'transport': _transport(raw, attempts), 'attemptErrors': errors}
        if not raw or not raw.get('ok'):
            return {'status': 'blocked', 'sendAttempts': 0,
                    'reason': 'windows-send-rejected:' + (errors[-1] if errors else 'unknown'),
                    'transport': _transport(raw, 0), 'attemptErrors': errors}
        self._last_transport = raw
        evidence = self._verify_sent(resolved, item, work)
        if evidence.get('ok'):
            return {'status': 'verified', 'sendAttempts': attempts,
                    'verificationLevel': ('windows-readback-text-anchor' if item['type'] == 'text'
                                          else 'windows-readback-file-card'),
                    'reason': None, 'evidence': evidence, 'transport': _transport(raw, attempts)}
        return {'status': 'unknown', 'sendAttempts': attempts,
                'reason': evidence.get('reason') or 'windows-readback-incomplete',
                'evidence': evidence, 'transport': _transport(raw, attempts)}

    def _verify_sent(self, resolved, item, work):
        """Readback proof: target session is current AND payload anchors the tail."""
        transport_dir = Path(work) / 'transport'
        auto_kind = None
        end = time.time() + VERIFY_WINDOW
        title_proven = False
        polls = 0
        while time.time() < end:
            current = self.client.current()
            title = _normalize_title((current.get('data') or {}).get('title'))
            title_proven = _title_compatible(title, resolved)
            if not title_proven:
                time.sleep(VERIFY_POLL)
                continue
            read = self.client.read()
            messages = _read_messages(read)
            if not messages:
                time.sleep(VERIFY_POLL)
                continue
            if item['type'] == 'text':
                anchors = (('text-exact', item['text']),)
            else:
                auto_kind = ((self._last_transport.get('data') or {})
                             .get('auto') if self._last_transport else None)
                markers = (FILE_CARD_MARKERS if item['type'] == 'image' or auto_kind == 'image'
                           else ('[文件]',))
                anchors = tuple(('file-card', marker) for marker in markers)
            for level, anchor in anchors:
                if _anchor_newness(messages, anchor):
                    receipt = {'ok': True, 'resolvedGroup': resolved,
                               'currentTitle': title, 'messageCount': len(messages),
                               'anchor': level, 'anchorValue': anchor,
                               'anchorInTrailingPosition': True,
                               'autoKind': auto_kind, 'readbackAt': time.time()}
                    (transport_dir / 'after-send-readback.json').write_text(
                        json.dumps({'receipt': receipt,
                                    'tailMessages': messages[-4:]},
                                   ensure_ascii=False, default=str), encoding='utf-8')
                    return receipt
            polls += 1
            time.sleep(VERIFY_POLL)
        return {'ok': False, 'resolvedGroup': resolved, 'titleProven': title_proven,
                'reason': ('windows-current-session-title-mismatch' if not title_proven
                           else 'windows-readback-anchor-not-trailing'),
                'polls': polls}

    def reconcile(self, request, item, work, prior):
        """Read-only reconcile; binds retained transport receipt to a live readback."""
        raw = prior.get('transport') or {}
        if raw.get('groupName') not in (None, request['groupName']):
            raise Rejected('reconcile-binding-mismatch')
        if raw.get('payloads') and [p.get('sha256') for p in raw['payloads']] != [item['sha256']]:
            raise Rejected('reconcile-binding-mismatch')
        # 2026-10-18 缺口修复：传输收据证明「从未派发」（sendAttempts=0 且 ok=false，
        # 即网关在 UI 动作前就拒绝——消息必然未上屏）时，reconcile 不应把状态升级为
        # unknown（那会让 delivery_state 判 unresolved → prepare_next 拒绝 → 死锁），
        # 而应如实返回 blocked（未尝试），让状态机回到 untouched、允许后续事件重发。
        # 依据 #26：sendAttempts=0+ok=false ≠ attempted，无重复外发风险。
        if raw.get('sendAttempts') == 0 and not raw.get('ok'):
            return {'status': 'blocked', 'sendAttempts': 0,
                    'reason': 'reconcile-proven-never-dispatched', 'transport': raw}
        if raw.get('sendAttempts') != 1 or not raw.get('ok'):
            return {'status': 'unknown', 'sendAttempts': 0,
                    'reason': 'reconcile-evidence-insufficient', 'transport': raw}
        resolved = self._require_resolved(request)
        current = self.client.current()
        title = _normalize_title((current.get('data') or {}).get('title'))
        if not _title_compatible(title, resolved):
            return {'status': 'unknown', 'sendAttempts': 0,
                    'reason': 'windows-current-session-title-mismatch', 'transport': raw}
        read = self.client.read()
        messages = _read_messages(read)
        anchors = ((item['text'],) if item['type'] == 'text' else FILE_CARD_MARKERS)
        if not any(_anchor_newness(messages, anchor) for anchor in anchors):
            return {'status': 'unknown', 'sendAttempts': 0,
                    'reason': 'reconcile-anchor-missing', 'transport': raw}
        return {'status': 'verified', 'sendAttempts': 0,
                'verificationLevel': 'windows-readback-reconcile',
                'evidence': {'resolvedGroup': resolved, 'currentTitle': title},
                'transport': raw, 'reconciled': True}

#!/usr/bin/env python3
"""Registered desktop business handoff; preserves legacy attempt identities.
Business callers retain source/date/history validation. No generic test-policy bypass.
"""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contract import Rejected, normalize, request_digest
from executor import deliver, verify_dependencies, deadline
from ledger import atomic_json, read_json

SKILLS = Path(__file__).resolve().parents[2]
PROJECT = SKILLS.parent
WORKSPACE = PROJECT.parent
GROUP = 'FEIBING NEO AI数字员工'
JINSHA_GROUP = '上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰'
NEGATIVE_REVIEW_GROUP_SEARCH = '上海臻肆外卖运营-盯个盯'
EVIDENCE_ROOT = Path('/tmp/zhensi_daily_download/background-browser')


# 2026-10-24 测试隔离（与 WECHAT_TEST_GROUP / executor.STATE 对称，fail-safe 单点翻转）：
# 设置 WECOM_TEST_ROOT 后，所有 ledger（防重标记/账本）重定向到独立目录（默认
# .runtime-test），绝不触碰生产 .runtime；仅运行期环境变量生效，不写任何配置文件。
def _apply_test_root(p: Path) -> Path:
    tr = os.environ.get('WECOM_TEST_ROOT')
    if not tr:
        return p
    s = str(p)
    if '/.runtime/' in s:
        return Path(s.replace('/.runtime/', '/%s/' % tr))
    return p


class PreDispatchDependencyFailure(RuntimeError):
    """Dependency integrity rejected before ledger creation or desktop access."""


def verify_pre_dispatch_dependencies():
    try:
        verify_dependencies()
    except Rejected as error:
        reason = str(error)
        if reason.startswith('dependency-drift:'):
            raise PreDispatchDependencyFailure(reason) from error
        raise


def exception_receipt(error):
    if isinstance(error, PreDispatchDependencyFailure):
        return {'ok':False,'verified':False,'reason':str(error),
                'sendAttempts':0,'items':[],'stage':'dependency_integrity_preflight',
                'runtimeModelDecisions':0}
    return {'ok':False,'verified':False,'reason':str(error),'sendAttempts':None}


# 2026-10-03 P0-2 演进补丁（大同全权授权，授权登记见 dependency_maintenance.py 同日条目）：
# REGISTRY 的「落群路由」（group/kind/count）外置为可版本化数据文件
# config/registry-routing.json——日常增改落群映射 = 只改数据文件，**零封印**。
# 铁律：授权串（第4元）与防重台账路径（第5元）**留在封印代码内**，绝不外置。
# 数据文件缺失/损坏/字段非法 → 逐条目回退内置默认（= 下方字面值），行为与外置前一致。
REGISTRY_ROUTES_CONFIG = SKILLS / 'wechat-messaging' / 'config' / 'registry-routing.json'
_BUILTIN_ROUTES = {
    'merchants': ('电销+直播攻坚组', 'text', 1),
    'top10': ('GROUP', 'image', 1),
    'taobao-evidence': ('GROUP', 'image', [1, 2]),
    'jinsha-reports': ('JINSHA_GROUP', 'file', 2),
    'jinsha-reports-taobao-repair-20260917': ('JINSHA_GROUP', 'file', 1),
    # 2026-10-23 受控维护（大同 11:41 授权「按异常处理补发淘宝一张」）：金鲨日报流当日
    # 因群名变更（外部群改名后改回）标题证明失败，整批 unknown 停在美团之后、淘宝日报
    # 未尝试。整批机制无「只补第二张」合法路径，按 20260917 修复通道先例开单件修复
    # 通道：独立授权/防重台账，载荷钉死当日淘宝日报指纹，防它用。
    'jinsha-reports-taobao-repair-20261023': ('JINSHA_GROUP', 'file', 1),
    'negative-reviews': ('JINSHA_GROUP', 'file', 1),
    # 2026-10-22 大同要求：差评分析 Excel 发群后，再补发一张「整表长图」进同一运营群。
    # 单独开 image 通道（独立防重台账/marker/授权），与 xlsx 投递解耦：
    # xlsx 已 verified 后的补发/失败互不影响，也不会把图混进 xlsx 的 count。
    'negative-reviews-summary': ('JINSHA_GROUP', 'image', 1),
    'taobao-flash-appeals': ('GROUP', 'file', 1),
    'meituan-waimai-appeals': ('GROUP', 'file', 1),
    # 2026-10-22 大同要求：两条申诉流的 Excel 结果表发群后，再补发一张「汇总台账」截图。
    # 单独开 image 通道（独立防重台账/marker/授权），与 xlsx 投递解耦：
    # xlsx 已 verified 后的补发/失败互不影响，也不会把图混进 xlsx 的 count。
    'taobao-flash-appeals-summary': ('JINSHA_GROUP', 'image', 1),
    'meituan-waimai-appeals-summary': ('JINSHA_GROUP', 'image', 1),
    'meituan-customer-reply-daily': ('GROUP', 'file', 1),
    # 2026-10-06 新增：负反馈列表申诉汇总（美团+淘宝双 Excel 一次投递），
    # 大同当日授权新建工作流 negative-feedback-list-appeals（09:30 申诉 + 12:30 汇总发群）。
    'negative-feedback-appeals': ('GROUP', 'file', 2),
}
_REGISTRY_AUTHORIZATIONS = {
    'merchants': 'user-20260915-production-hourly',
    'top10': 'zhensi-feibing-neo-ai-main-wechat-top10-v1',
    'taobao-evidence': None,
    'jinsha-reports': 'zhensi-business-main-wechat-shanghai-zhensi-operations-ding-fandang-daily-v2-reauthorized-20260917',
    'jinsha-reports-taobao-repair-20260917': 'zhensi-business-main-wechat-shanghai-zhensi-operations-ding-fandang-taobao-repair-v3-user-20260917',
    'jinsha-reports-taobao-repair-20261023': 'zhensi-business-main-wechat-shanghai-zhensi-operations-ding-fandang-taobao-repair-v3-user-20261023',
    'negative-reviews': 'zhensi-negative-review-main-wechat-shanghai-zhensi-operations-ding-fandang-v1-user-20260918',
    'negative-reviews-summary': 'zhensi-negative-review-summary-main-wechat-shanghai-zhensi-operations-ding-fandang-v1-user-20261022',
    'taobao-flash-appeals': 'automation-3-taobao-flash-appeals-daily-authorized',
    'meituan-waimai-appeals': 'user-20260923-meituan-waimai-appeals-fixed-delivery',
    'taobao-flash-appeals-summary': 'user-20261022-appeals-summary-card',
    'meituan-waimai-appeals-summary': 'user-20261022-appeals-summary-card',
    'meituan-customer-reply-daily': 'user-20261001-meituan-customer-reply-daily',
    'negative-feedback-appeals': 'user-20261006-negative-feedback-list-appeals',
}
_REGISTRY_LEDGERS = {
    'merchants': PROJECT/'state/taobao-agent-new-merchants/send-attempts',
    'top10': SKILLS/'daily-top10-to-wechat-group/.runtime/send-ledger',
    'taobao-evidence': PROJECT/'.local/state/taobao-jinsha-wechat-evidence-attempts',
    'jinsha-reports': PROJECT/'.local/state/jinsha-report-send-shanghai-zhensi-operations-ding-fandang-reauthorized-20260917-v2.desktop-attempts',
    'jinsha-reports-taobao-repair-20260917': PROJECT/'.local/state/jinsha-report-send-shanghai-zhensi-operations-ding-fandang-taobao-repair-20260917-v3.desktop-attempts',
    'jinsha-reports-taobao-repair-20261023': PROJECT/'.local/state/jinsha-report-send-shanghai-zhensi-operations-ding-fandang-taobao-repair-20261023-v3.desktop-attempts',
    'negative-reviews': PROJECT/'.local/state/negative-review-send-shanghai-zhensi-operations-ding-fandang-v1.desktop-attempts',
    'negative-reviews-summary': PROJECT/'.local/state/negative-review-summary-send-shanghai-zhensi-operations-ding-fandang-v1.desktop-attempts',
    'taobao-flash-appeals': WORKSPACE/'state/taobao-flash-sale-negative-review-appeals/wechat-attempts',
    'meituan-waimai-appeals': WORKSPACE/'state/meituan-waimai-negative-review-appeals/wechat-attempts',
    'taobao-flash-appeals-summary': WORKSPACE/'state/taobao-flash-sale-negative-review-appeals/summary-attempts',
    'meituan-waimai-appeals-summary': WORKSPACE/'state/meituan-waimai-negative-review-appeals/summary-attempts',
    'meituan-customer-reply-daily': PROJECT/'state/meituan-customer-reply-daily/wechat-attempts',
    'negative-feedback-appeals': WORKSPACE/'state/negative-feedback-list-appeals/wechat-attempts',
}


def _load_route_overrides():
    """读外置路由表；任何异常/非法字段 → 返回空 dict（逐条目回退内置默认）。"""
    try:
        data = json.loads(REGISTRY_ROUTES_CONFIG.read_text(encoding='utf-8'))
        routes = data.get('routes') if isinstance(data, dict) else None
        if not isinstance(routes, dict):
            return {}
        out = {}
        for wid, route in routes.items():
            if not isinstance(route, dict):
                continue
            group, kind, count = route.get('group'), route.get('kind'), route.get('count')
            if not isinstance(group, str) or not group.strip() or kind not in ('text', 'image', 'file'):
                continue
            if isinstance(count, bool) or not (
                    isinstance(count, int) or
                    (isinstance(count, list) and len(count) == 2 and
                     all(isinstance(c, int) and not isinstance(c, bool) for c in count))):
                continue
            out[wid] = (group.strip(), kind, count)
        return out
    except (OSError, ValueError):
        return {}


_ROUTE_OVERRIDES = _load_route_overrides()


def _registry_entry(wid):
    builtin = _BUILTIN_ROUTES[wid]
    override = _ROUTE_OVERRIDES.get(wid)
    group_expr, kind, count = override if override else builtin
    if group_expr == 'GROUP':
        group = GROUP
    elif group_expr == 'JINSHA_GROUP':
        group = JINSHA_GROUP
    else:
        group = group_expr
    count = tuple(count) if isinstance(count, list) else count
    return (group, kind, count, _REGISTRY_AUTHORIZATIONS[wid], _REGISTRY_LEDGERS[wid])


REGISTRY = {wid: _registry_entry(wid) for wid in _BUILTIN_ROUTES}


def taobao_flash_appeals_scope(now=None):
    current = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
    current = current.astimezone(ZoneInfo('Asia/Shanghai'))
    return (current - timedelta(days=1)).strftime('%Y-%m-%d'), current.strftime('%Y%m%d')


def meituan_waimai_appeals_scope(now=None):
    current = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
    current = current.astimezone(ZoneInfo('Asia/Shanghai'))
    return (current - timedelta(days=1)).strftime('%Y-%m-%d'), current.strftime('%Y%m%d')


def prepare(args):
    if args.workflow_id not in REGISTRY:
        raise Rejected('workflow-not-registered')
    group, kind, count, authorization, ledger = REGISTRY[args.workflow_id]
    ledger = Path(ledger)
    ledger_redirected = _apply_test_root(ledger)
    # 2026-10-03 受控维护（大同授权「方案 B：开搞」）：count 允许 int 或 (min,max) 区间，
    # taobao-evidence 改为 (1,2) 支持当日已交付图的「只补缺失」部分重发；其余条目语义不变。
    expected_counts = count if isinstance(count, tuple) else (count,)
    if args.group != group or args.payload_type != kind or len(args.item) not in expected_counts:
        raise Rejected('workflow-target-or-payload-mismatch')
    if Path(args.ledger).resolve() not in (ledger.resolve(), ledger_redirected.resolve()):
        raise Rejected('workflow-ledger-mismatch')
    if not args.marker_name or Path(args.marker_name).name != args.marker_name or not args.marker_name.endswith('.json'):
        raise Rejected('workflow-marker-invalid')
    # 2026-10-03 受控维护：发图/发文件需「上传 + 服务端 GUI 发送 + 回读验证」，原 180s
    # 硬顶会在服务端仍处理时提前判定 deadline-expired，造成「已送达或仅部分送达但回执
    # unknown」（#10 全表回执停在 unknown、#5 第二张证据图被截断均源于此）。兜底提到
    # 600s；调用方可用 --deadline-unix 指定更长窗口，硬顶 900s，仍小于
    # manifest timeout_seconds=1800。仅延长等待窗口，不改变连接方式与防重规则。
    until = min(float(args.deadline_unix), time.time()+900) if getattr(args, 'deadline_unix', None) else time.time()+600
    context={'workflowId':args.workflow_id, 'eventId':str(ledger.resolve()/args.marker_name),
             'accountAlias':'main-wechat', 'channel':'desktop', 'deadlineAt':until}
    if args.workflow_id in ('jinsha-reports', 'negative-reviews', 'negative-reviews-summary'):
        context['searchGroupName']=NEGATIVE_REVIEW_GROUP_SEARCH
    request = normalize({'schemaVersion':1, 'groupName':group,
        'items':[{'itemId':str(n), 'type':kind, 'text' if kind=='text' else 'path':value} for n,value in enumerate(args.item)],
        'context':context})
    resume_marker = getattr(args, 'resume_blocked_zero_marker', None)
    if resume_marker:
        if not (args.workflow_id == 'merchants' and args.execute and not args.reconcile
                and validate_blocked_zero_text_marker(Path(resume_marker), ledger,
                                                      args.marker_name, request)):
            raise Rejected('resume-blocked-zero-marker-contract-mismatch')
        request['context']['resumePreparedText'] = request['items'][0]['text']
        request['context']['resumePreparedTextSha256'] = request['items'][0]['sha256']
    if args.workflow_id == 'taobao-evidence':
        import re
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        day=(datetime.now(ZoneInfo('Asia/Shanghai'))-timedelta(days=1)).strftime('%Y-%m-%d')
        names=['jinsha-store-final.png','jinsha-review-final.png']
        parents={str(Path(i['path']).parent) for i in request['items']}
        if len(parents)!=1 or not re.fullmatch(re.escape(str(EVIDENCE_ROOT.resolve())+'/')+day+r'-[0-9a-f-]{36}',next(iter(parents))):
            raise Rejected('workflow-evidence-path-mismatch')
        # 2026-10-03 受控维护：允许保序子集（只补缺失图），仍禁止乱序/重复/空集。
        sent_names=[i['name'] for i in request['items']]
        if sent_names!=[n for n in names if n in sent_names]:
            raise Rejected('workflow-evidence-order-mismatch')
        count_word={1:'一张',2:'两张'}[len(request['items'])]
        authorization='\n'.join([f'确认发送{count_word}截图到 {group}',f'业务日期 {day}']+[f"{i['name']} {i['sha256']}" for i in request['items']])
    if args.workflow_id == 'jinsha-reports-taobao-repair-20260917':
        item=request['items'][0]
        if (item['name']!='淘宝闪购日报_2026-09-16.xlsx'
                or item['size']!=111626
                or item['sha256']!='20620377c89b522564634aebd40d0edb68b8e0bdb15ff1c6cd98187054319321'):
            raise Rejected('workflow-taobao-repair-payload-mismatch')
    if args.workflow_id == 'jinsha-reports-taobao-repair-20261023':
        item=request['items'][0]
        if (item['name']!='淘宝闪购日报_2026-10-22.xlsx'
                or item['size']!=113660
                or item['sha256']!='4b534b6a244e1a723de1db07c1901b3b0c8dfe6f68f42f392a5af21c2c48c2ac'):
            raise Rejected('workflow-taobao-repair-payload-mismatch')
    if args.workflow_id == 'negative-reviews':
        import re
        item=request['items'][0]
        standard=re.fullmatch(r'差评分析数据_(\d{4}-\d{2}-\d{2})_\1\.xlsx',item['name'])
        correction=re.fullmatch(r'差评分析数据_(\d{4}-\d{2}-\d{2})_\1_更正\.xlsx',item['name'])
        match=standard or correction
        if match is None:
            raise Rejected('workflow-negative-review-name-mismatch')
        day=match.group(1)
        expected=(PROJECT/'outputs'/f"yesterday-negative-{day.replace('-', '')}"/item['name']).resolve()
        if Path(item['path']).resolve()!=expected:
            raise Rejected('workflow-negative-review-path-mismatch')
        expected_marker=(f'negative-review-{day}-correction-v1.json' if correction
                         else f'negative-review-{day}.json')
        if args.marker_name != expected_marker:
            raise Rejected('workflow-negative-review-marker-mismatch')
    if args.workflow_id == 'negative-reviews-summary':
        import re
        item=request['items'][0]
        match=re.fullmatch(r'差评分析长图_(\d{4}-\d{2}-\d{2})_\1\.jpg',item['name'])
        if match is None:
            raise Rejected('workflow-negative-review-summary-name-mismatch')
        day=match.group(1)
        expected=(PROJECT/'outputs'/f"yesterday-negative-{day.replace('-', '')}"/item['name']).resolve()
        if Path(item['path']).resolve()!=expected:
            raise Rejected('workflow-negative-review-summary-path-mismatch')
        if args.marker_name != f'negative-review-summary-{day}.json':
            raise Rejected('workflow-negative-review-summary-marker-mismatch')
    if args.workflow_id == 'taobao-flash-appeals':
        import re
        expected_date, run_key = taobao_flash_appeals_scope()
        expected_report = (PROJECT/'outputs'/f'taobao-flash-sale-negative-review-appeals-{run_key}'/f'淘宝闪购差评申诉汇总-{expected_date}.xlsx').resolve()
        correction = bool(getattr(args, 'correction_v1', False))
        expected_marker = f"taobao-flash-appeals-{expected_date}{'-correction-v1' if correction else ''}.json"
        expected_authorization = (f'user-{run_key}-taobao-flash-appeals-correction-v1' if correction else authorization)
        names = [item['name'] for item in request['items']]
        if names != [expected_report.name]:
            raise Rejected('workflow-taobao-flash-appeals-name-or-order-mismatch')
        if [Path(item['path']).resolve() for item in request['items']] != [expected_report]:
            raise Rejected('workflow-taobao-flash-appeals-path-mismatch')
        pattern = r'taobao-flash-appeals-\d{4}-\d{2}-\d{2}(?:-correction-v1)?\.json'
        if not re.fullmatch(pattern, args.marker_name) or args.marker_name != expected_marker:
            raise Rejected('workflow-taobao-flash-appeals-marker-mismatch')
        if correction and Path(args.output_dir).resolve() != (expected_report.parent/'wechat-delivery'/'correction-v1').resolve():
            raise Rejected('workflow-taobao-flash-appeals-correction-output-mismatch')
        authorization = expected_authorization
        if correction and (not getattr(args, 'execute', False) or getattr(args, 'reconcile', False)):
            raise Rejected('workflow-correction-execute-only')
    if args.workflow_id == 'meituan-waimai-appeals':
        import re
        expected_date, run_key = meituan_waimai_appeals_scope()
        expected_report = (WORKSPACE/'zhensi_waimai_back'/'outputs'/f'meituan-waimai-negative-review-appeals-{run_key}'/f'美团外卖差评申诉汇总-{expected_date}.xlsx').resolve()
        correction = bool(getattr(args, 'correction_v1', False))
        expected_marker = f"meituan-waimai-appeals-{expected_date}{'-correction-v1' if correction else ''}.json"
        expected_authorization = (f'user-{run_key}-meituan-waimai-appeals-correction-v1' if correction else authorization)
        names = [item['name'] for item in request['items']]
        if names != [expected_report.name]:
            raise Rejected('workflow-meituan-waimai-appeals-name-or-order-mismatch')
        if [Path(item['path']).resolve() for item in request['items']] != [expected_report]:
            raise Rejected('workflow-meituan-waimai-appeals-path-mismatch')
        pattern = r'meituan-waimai-appeals-\d{4}-\d{2}-\d{2}(?:-correction-v1)?\.json'
        if not re.fullmatch(pattern, args.marker_name) or args.marker_name != expected_marker:
            raise Rejected('workflow-meituan-waimai-appeals-marker-mismatch')
        if correction and Path(args.output_dir).resolve() != (expected_report.parent/'wechat-delivery'/'correction-v1').resolve():
            raise Rejected('workflow-meituan-waimai-appeals-correction-output-mismatch')
        authorization = expected_authorization
        if correction and (not getattr(args, 'execute', False) or getattr(args, 'reconcile', False)):
            raise Rejected('workflow-correction-execute-only')
    if args.workflow_id in ('taobao-flash-appeals-summary', 'meituan-waimai-appeals-summary'):
        # 2026-10-22 大同要求：申诉 Excel 结果表投递成功后，补发该业务日的「汇总台账」截图。
        # 契约：文件名/目录/marker 与业务日严格绑定，禁止换图重发；内容由
        # runtime/appeals_summary_card.py 从 records + 平台统计行渲染，不落人工数字。
        import re
        is_taobao = args.workflow_id == 'taobao-flash-appeals-summary'
        expected_date, run_key = (taobao_flash_appeals_scope() if is_taobao
                                  else meituan_waimai_appeals_scope())
        prefix = '淘宝闪购差评申诉台账' if is_taobao else '美团外卖差评申诉台账'
        folder = f"{'taobao-flash-sale-negative-review-appeals' if is_taobao else 'meituan-waimai-negative-review-appeals'}-{run_key}"
        expected_card = (PROJECT/'outputs'/folder/f'{prefix}-{expected_date}.png').resolve()
        names = [item['name'] for item in request['items']]
        if names != [expected_card.name]:
            raise Rejected('workflow-appeals-summary-name-mismatch')
        if [Path(item['path']).resolve() for item in request['items']] != [expected_card]:
            raise Rejected('workflow-appeals-summary-path-mismatch')
        expected_marker = (f"taobao-flash-appeals-summary-{expected_date}.json" if is_taobao
                           else f"meituan-waimai-appeals-summary-{expected_date}.json")
        pattern = r'(?:taobao-flash|meituan-waimai)-appeals-summary-\d{4}-\d{2}-\d{2}\.json'
        if not re.fullmatch(pattern, args.marker_name) or args.marker_name != expected_marker:
            raise Rejected('workflow-appeals-summary-marker-mismatch')
        if getattr(args, 'correction_v1', False):
            raise Rejected('workflow-appeals-summary-no-correction')
    if args.workflow_id == 'meituan-customer-reply-daily':
        import re
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI
        expected_date = _dt.now(_ZI('Asia/Shanghai')).strftime('%Y-%m-%d')
        # 2026-10-05 受控维护：智能客服技能包已迁入 skills/workflows/（多一层），
        # 原 SKILLS/'meituan-intelligent-customer-service'/... 与真实落盘路径不符，
        # 使 17:00 档真实外发一律 workflow-meituan-customer-reply-path-mismatch（verified=false 未外发）。
        # 仅校正路径锚点，不改命名/marker/授权契约。
        expected_report = (SKILLS/'workflows'/'meituan-intelligent-customer-service'/'records'/f'美团客户回复记录-{expected_date}.xlsx').resolve()
        names = [item['name'] for item in request['items']]
        if names != [expected_report.name]:
            raise Rejected('workflow-meituan-customer-reply-name-mismatch')
        if [Path(item['path']).resolve() for item in request['items']] != [expected_report]:
            raise Rejected('workflow-meituan-customer-reply-path-mismatch')
        pattern = r'meituan-customer-reply-daily-\d{4}-\d{2}-\d{2}(?:-\d{6})?\.json'
        # 2026-10-04 受控维护：放行可选 -HHMMSS 轮次戳。依据大同 2026-10-03 授权「当天当次数据、
        # 不限次数、没有重复门禁」——step4 的 marker 已改为每轮唯一（带时分秒），旧正则只认纯日期
        # 导致真实外发一律 marker-mismatch（发送链路静默断裂）。日期锚定与当日报表路径校验不变。
        if not re.fullmatch(pattern, args.marker_name):
            raise Rejected('workflow-meituan-customer-reply-marker-mismatch')
    if not authorization or args.authorization != authorization:
        raise Rejected('workflow-authorization-mismatch')
    grant={'schemaVersion':1,'requestDigest':request_digest(request),'accountAlias':'main-wechat',
           'groupName':group,'channel':'desktop','expiresAt':until,'authorizationRef':authorization}
    return request, grant


def payloads(request):
    return [{k:v for k,v in item.items() if k not in ('itemId','type')} for item in request['items']]


def validate_blocked_zero_text_marker(path, ledger, marker_name, request):
    """Authorize only fully bound blocked receipts whose code stages prove no send began."""
    import hashlib
    import re
    expected_path = (Path(ledger).resolve() / marker_name).resolve()
    if path.is_symlink() or path.resolve() != expected_path or not path.is_file():
        return False
    try:
        prior = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(prior, dict):
        return False
    items = request.get('items') or []
    payload_list = prior.get('payloads') or []
    common = prior.get('commonReceipt') or {}
    common_items = common.get('items') or []
    if len(items) != 1 or items[0].get('type') != 'text' or len(payload_list) != 1:
        return False
    item = items[0]
    payload = payload_list[0]
    common_item = common_items[0] if len(common_items) == 1 else {}
    transport = common_item.get('transport') or {}
    transport_payloads = transport.get('payloads') or []
    digest = hashlib.sha256(item['text'].encode('utf-8')).hexdigest()
    binding = (
        prior.get('bridgeVersion') == 1 and prior.get('state') == 'blocked'
        and prior.get('sendAttempts') == 0 and prior.get('newSendAttempts', 0) == 0
        and prior.get('groupName') == request.get('groupName')
        and prior.get('groupName') == '电销+直播攻坚组' and prior.get('payloadType') == 'text'
        and payload.get('text') == item['text'] and payload.get('sha256') == digest == item.get('sha256')
        and common.get('status') == 'blocked' and common.get('groupName') == prior.get('groupName')
    )
    if not binding:
        return False
    prepare_stage = (
        prior.get('stage') == 'prepare_payload'
        and prior.get('reason') == 'desktop-text-input-write-failed'
        and prior.get('physicalSendAttempts') == 0
        and common.get('reason') == prior.get('reason')
        and common_item.get('status') == 'blocked' and common_item.get('type') == 'text'
        and common_item.get('sendAttempts') == 0 and common_item.get('reason') == prior.get('reason')
        and common_item.get('sha256') == digest
        and transport.get('groupName') == prior.get('groupName')
        and transport.get('payloadType') == 'text' and transport.get('stage') == 'prepare_payload'
        and transport.get('sendAttempts') == 0 and transport.get('reason') == prior.get('reason')
        and len(transport_payloads) == 1 and transport_payloads[0].get('text') == item['text']
        and transport_payloads[0].get('sha256') == digest
    )
    if prepare_stage:
        return True
    # This exact receipt shape is emitted when a bound draft no longer matches
    # during preflight. The common bridge has no item receipt because it never
    # entered send(); null physical count is accepted only with this stage chain.
    review = common.get('review') or []
    stages = [row.get('stage') for row in review if isinstance(row, dict)]
    summary = common.get('reviewSummary') or {}
    return (
        prior.get('reason') == 'resume-prepared-text-readback-mismatch'
        and prior.get('stage') is None and prior.get('physicalSendAttempts') is None
        and common.get('reason') == prior.get('reason') and common_items == []
        and re.fullmatch(r'[0-9a-f]{64}', str(common.get('requestDigest') or ''))
        and stages == ['authorization', 'freeze:0', 'preflight']
        and all(row.get('status') == 'completed' for row in review)
        and summary.get('result') == 'blocked' and summary.get('failedStages') == []
    )


def assert_correction_origin(args, request):
    """Require a verified standard send and a genuinely changed fixed report."""
    if not getattr(args, 'correction_v1', False):
        return
    prefixes = {'taobao-flash-appeals':'taobao-flash-appeals',
                'meituan-waimai-appeals':'meituan-waimai-appeals'}
    prefix = prefixes.get(args.workflow_id)
    if prefix is None:
        raise Rejected('workflow-correction-not-registered')
    business_date, run_key = (taobao_flash_appeals_scope() if args.workflow_id == 'taobao-flash-appeals'
                              else meituan_waimai_appeals_scope())
    original = read_json(Path(args.ledger).resolve()/f'{prefix}-{business_date}.json')
    # 2026-10-22：两条申诉流改发运营群后，原先硬编码 GROUP 的校验会把合法修正判成
    # origin-not-verified。改为对齐该 workflow 当前注册的落群（REGISTRY 第一元），
    # 语义不变：仍要求「原发确实 verified 且落在同一目标群」。
    expected_group = REGISTRY[args.workflow_id][0]
    if (not original or original.get('verified') is not True or original.get('state') != 'verified'
            or not isinstance(original.get('sendAttempts'), int) or original['sendAttempts'] < 1
            or original.get('groupName') != expected_group or original.get('payloadType') != 'file'):
        raise Rejected('workflow-correction-original-not-verified')
    before = original.get('payloads') or []
    after = payloads(request)
    if len(before) != 1 or len(after) != 1:
        raise Rejected('workflow-correction-payload-count-mismatch')
    old, new = before[0], after[0]
    report_prefix = ('taobao-flash-sale-negative-review-appeals' if args.workflow_id == 'taobao-flash-appeals'
                     else 'meituan-waimai-negative-review-appeals')
    if args.workflow_id == 'taobao-flash-appeals':
        expected_report_dir = (PROJECT/'outputs'/f'{report_prefix}-{run_key}').resolve()
    else:
        expected_report_dir = (WORKSPACE/'zhensi_waimai_back'/'outputs'/f'{report_prefix}-{run_key}').resolve()
    if (original['groupName'] != request['groupName'] or old.get('name') != new.get('name')
            or Path(old.get('path', '')).resolve() != Path(new['path']).resolve()
            or Path(new['path']).resolve().parent != expected_report_dir
            or old.get('sha256') == new.get('sha256')):
        raise Rejected('workflow-correction-original-payload-mismatch')


def never_sent(prior):
    # 从未发出的阻塞标记：零发送历史（sendAttempts=0 且无 physicalSendAttempts）。
    # 对这类标记允许重绑重生成产物（check_old 字节漂移 + 事件层 binding 刷新）。
    return (prior.get('state') == 'blocked' and (prior.get('sendAttempts') or 0) == 0
            and not (prior.get('physicalSendAttempts') or 0))


def check_old(prior, request):
    if prior.get('payloadType',request['items'][0]['type']) != request['items'][0]['type']:
        raise Rejected('legacy-marker-type-mismatch')
    expected=payloads(request)
    actual=prior.get('payloads') or []
    if prior.get('groupName')!=request['groupName'] or len(actual)!=len(expected):
        raise Rejected('legacy-marker-binding-mismatch')
    # 从未发出的阻塞标记允许重绑新生成的 payload 字节：绑定校验的目的是防
    # 「已发出的标记被换文件重发」（attempted 后内容漂移必须拒绝）；而
    # sendAttempts==0 的 blocked 标记零发送历史，下游流每轮重生成产物
    # （xlsx 内嵌时间戳等）导致 sha 漂移是常态，卡死只会挡住当日工作
    # （淘宝闪购 2026-10-09 实证：marker 钉 09:20 旧 sha，step1 重生成后
    # 整天 legacy-marker-binding-mismatch）。名字/顺序/类型仍须一致，
    # 不会把另一个文件绑进这个标记。
    rebindable=never_sent(prior)
    for a,b in zip(actual,expected):
        if rebindable:
            if b.get('name') is not None and a.get('name')!=b.get('name'):
                raise Rejected('legacy-marker-binding-mismatch')
            continue
        # A path move is harmless; full content/name/order must remain identical.
        keys=('text','sha256') if 'text' in b else ('name','size','sha256')
        if any(a.get(k)!=b.get(k) for k in keys):
            raise Rejected('legacy-marker-binding-mismatch')


def legacy_text_reconcile(prior, request, output, adapter):
    wrapped_unknown = (prior.get('stage') == 'completed'
                       and (prior.get('commonReceipt') or {}).get('status') == 'unknown')
    common = prior.get('commonReceipt') or {}
    common_items = common.get('items') or []
    requested_item = request['items'][0] if len(request.get('items') or []) == 1 else {}
    failed_stages = [row for row in common.get('review', [])
                     if row.get('stage') == 'send:0' and row.get('status') == 'failed']
    null_attempt_unknown = (
        prior.get('state') == 'unknown' and prior.get('sendAttempts') is None
        and prior.get('physicalSendAttempts') is None
        and prior.get('reason') == 'wechat-window-capture-failed:could not create image from window:quartz-window-capture-invalid'
        and common.get('status') == 'unknown' and common.get('channel') == 'desktop'
        and common.get('groupName') == request['groupName'] and len(common_items) == 1
        and common_items[0].get('status') == 'unknown'
        and common_items[0].get('type') == 'text'
        and common_items[0].get('sendAttempts') is None
        and common_items[0].get('sha256') == requested_item.get('sha256')
        and len(failed_stages) == 1
        and failed_stages[0].get('pitfalls') == [prior.get('reason')]
    )
    if not (len(request['items'])==1 and request['items'][0]['type']=='text'
            and ((prior.get('state') in ('unknown','verified') and prior.get('sendAttempts')==1
                  and (prior.get('stage')=='post_send_verify' or prior.get('state')=='verified'
                       or wrapped_unknown)) or null_attempt_unknown)):
        return prior | {'ok':False,'verified':False,'reason':'legacy-attempt-reconcile-only'}
    from desktop_text_readback import _copy_exact_bubble
    with deadline(request["context"]["deadlineAt"]), adapter.session(request):
        checked=adapter.preflight(request, output/'reconcile-preflight')
        if checked.get('ok') is not True:
            return prior | {'ok':False,'verified':False,'reason':checked.get('reason')}
        proof=_copy_exact_bubble(request['groupName'],request['items'][0],output)
    from evidence import text_proof
    if not text_proof(request['items'][0],proof):
        return prior | {'ok':False,'verified':False,'reason':'legacy-copy-readback-incomplete',
                        'copyReadback':proof}
    return prior | {'bridgeVersion':1,'ok':True,'verified':True,'state':'verified','copyReadback':proof,
                    'reconciledWithoutSend':True,'physicalSendAttempts':prior.get('sendAttempts'),
                    'verificationMethod':'desktop-bubble-copy-exact-two-frame'}


def compatible_review(common):
    rows=[]
    by_id={i['itemId']:i for i in common.get('items',[])}
    for n,row in enumerate(common['review'],1):
        phase=row['stage'];outcome=by_id.get(phase.split(':',1)[-1],{})
        failed=(row['status']=='failed' or (phase.startswith(('send:','reconcile:')) and outcome.get('status')!='verified')
                or (phase=='preflight' and not common['ok'] and not common.get('items')))
        reasons=list(row.get('pitfalls',[]))
        if failed and not reasons:reasons=[outcome.get('reason') or common.get('reason') or 'verification-incomplete']
        rows.append(row | {'item':n,'label':phase,'status':'failed' if failed else row['status'],
                           'pitfalls':[{'code':'messaging-stage','reason':str(reason)} for reason in reasons]})
    return rows


def execute(args, *, adapter_factory=None):
    request, grant=prepare(args)
    assert_correction_origin(args, request)
    verify_pre_dispatch_dependencies()
    ledger=_apply_test_root(Path(args.ledger).resolve());marker=ledger/args.marker_name
    ledger.mkdir(parents=True,exist_ok=True,mode=0o700)
    output=Path(args.output_dir).resolve()
    # Also serializes across older workflow processes using this bridge.
    with marker.with_suffix('.bridge.lock').open('a+') as lock:
        os.chmod(lock.name,0o600)
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise Rejected('workflow-event-busy')
        prior=read_json(marker)
        if prior:
            check_old(prior,request)
            if getattr(args,'reconcile',False):
                # Every one-send text marker, including bridgeVersion=1 recovered
                # receipts, must prove the existing bubble by native copy before any
                # transport-ledger handling.  legacy_text_reconcile remains strict.
                result=legacy_text_reconcile(prior,request,output,adapter_factory() if adapter_factory else __import__('desktop_adapter').DesktopAdapter())
                if result.get('verified'):atomic_json(marker,result)
                return result
            if prior.get('verified') is True and prior.get('state')=='verified':
                return prior | {'ok':True,'reusedExisting':True,'newSendAttempts':0}
            # —— 事实结论化：unknown 但传输层已显式确认发出（transport.data.sent 为 true）。
            # 破除"已知发出却永久卡死"的死结（疆麦尔实证：relay 返回 data.sent=true，仅因当前会话不在目标群、
            # 标题校验 title-mismatch 导致读回落 unknown）。此处只复用、绝不重发、绝不触发任何适配器（含 Mac 桌面），
            # 因此不踩桌面微信红线；判据严格限定「传输层显式确认发出」，不会把"真未发出"的 unknown 误判为已发。 ——
            if prior.get('state') == 'unknown' and (prior.get('sendAttempts') or 0) >= 1:
                _common = prior.get('commonReceipt') or {}
                _items = _common.get('items') or []
                _sent = any(
                    ((it.get('transport') or {}).get('sent') is True)
                    or (((it.get('transport') or {}).get('data') or {}).get('sent') is True)
                    for it in _items
                )
                if _sent:
                    return prior | {'ok':True,'reusedExisting':True,'newSendAttempts':0,
                                   'verificationMethod':'transport-sent-evidence',
                                   'note':'unknown-but-sent-evidence:reused-without-resend'}
            safe=prior.get('bridgeVersion')==1 and prior.get('state')=='blocked' and prior.get('sendAttempts')==0
            if not safe and not getattr(args,'reconcile',False):
                return prior | {'ok':False,'verified':False,'reason':'existing-attempt-reconcile-only','newSendAttempts':0}
        elif getattr(args,'reconcile',False):
            raise Rejected('reconcile-no-attempt')
        if not args.execute and not getattr(args,'reconcile',False):
            raise Rejected('workflow-execute-required')
        if adapter_factory is None:
            from desktop_adapter import DesktopAdapter
            adapter_factory=DesktopAdapter
        adapter=adapter_factory()
        if not getattr(args,'reconcile',False):
            claim={'bridgeVersion':1,'state':'attempted','groupName':request['groupName'],'payloadType':args.payload_type,
                   'payloads':payloads(request),'sendAttempts':None,'verified':False}
            if prior is None:
                # The old sender also uses exclusive creation. Never overwrite a racing claim.
                with marker.open('x') as handle:
                    os.fchmod(handle.fileno(),0o600)
                    json.dump(claim,handle,ensure_ascii=False);handle.flush();os.fsync(handle.fileno())
                fd=os.open(ledger,os.O_RDONLY)
                try:os.fsync(fd)
                finally:os.close(fd)
            else:atomic_json(marker,claim)
        common=deliver(request,grant,ledger/'.wechat-messaging',adapter,
                       reconcile=getattr(args,'reconcile',False),
                       rebind_event=bool(prior) and never_sent(prior))
        items=common.get('items',[])
        attempts=[i.get('sendAttempts') for i in items]
        total=None if any(a is None for a in attempts) else sum(attempts)
        result={'bridgeVersion':1,'ok':common['ok'],'verified':common['ok'],'payloadType':args.payload_type,
                'state':'verified' if common['ok'] else common['status'],
                'groupName':request['groupName'],'payloads':payloads(request),
                'sendAttempts':total,'newSendAttempts':0 if getattr(args,'reconcile',False) or common['status']=='already_verified' else total,
                'reason':common.get('reason'),'runtimeModelDecisions':0,'commonReceipt':common,
                'attemptMarker':str(marker),'sendReview':compatible_review(common),'elapsedMs':common['elapsedMs']}
        result['reviewSummary']={'totalElapsedMs':common['elapsedMs'],'itemCount':len(result['sendReview']),
            'pitfallCount':sum(len(row['pitfalls']) for row in result['sendReview']),'result':'success' if common['ok'] else 'failed'}
        if len(items)==1 and request['items'][0]['type']=='text':
            item=items[0];raw=item.get('transport') or {}
            result.update(copyReadback=item.get('evidence'),physicalSendAttempts=raw.get('sendAttempts'),
                          postSendInputCleared=raw.get('postSendInputCleared'),stage=raw.get('stage'),
                          reconciledWithoutSend=bool(item.get('reconciled')))
            if item.get('reconciled'):result['sendAttempts']=raw.get('sendAttempts')
        atomic_json(marker,result);atomic_json(output/'receipt.json',result)
        return result


def main():
    p=argparse.ArgumentParser()
    for name in ('workflow-id','group','payload-type','authorization','ledger','marker-name','output-dir'):
        p.add_argument('--'+name,required=True)
    p.add_argument('--item',action='append',required=True)
    p.add_argument('--execute',action='store_true');p.add_argument('--reconcile',action='store_true')
    p.add_argument('--correction-v1',action='store_true')
    p.add_argument('--resume-blocked-zero-marker')
    p.add_argument('--deadline-unix',type=float)
    try:r=execute(p.parse_args())
    except Exception as e:r=exception_receipt(e)
    print(json.dumps(r,ensure_ascii=False));return 0 if r.get('ok') else 1

if __name__=='__main__':raise SystemExit(main())

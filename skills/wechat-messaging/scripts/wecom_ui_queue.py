"""Original adapter transport handoff to the authorized visible-UI post."""
import hashlib
import json
import time
import uuid
from pathlib import Path
from ledger import atomic_json

QUEUE = Path(__file__).resolve().parents[1] / '.runtime/ui-post-queue'
ALLOWED = {'negative-reviews-summary'}
NO_RESEND_STATE = Path(__file__).resolve().parents[3] / 'runtime/state'

def user_no_resend_today(workflow, *, now=None, state=None):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    day = now.strftime('%Y%m%d')
    record = (state or NO_RESEND_STATE) / f'user-no-resend-{day}-opening-taskrate.json'
    if not record.exists():
        return False
    try:
        data = json.loads(record.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return workflow in ('daily-new-stores-opening-to-wechat', 'daily-store-task-completion-ops')
    return (data.get('date') == now.strftime('%Y-%m-%d')
            and data.get('source') == 'explicit-user-instruction'
            and data.get('noMoreSendsToday') is True
            and workflow in data.get('workflows', []))

def enabled(request):
    context = request.get('context', {})
    if user_no_resend_today(context.get('workflowId')):
        return False
    from presentation_policy import violation
    if any(violation(item) for item in request.get('items', [])): return False
    if context.get('supplementAuthorization'):
        import sys
        runtime = Path(__file__).resolve().parents[3] / 'runtime'
        if str(runtime) not in sys.path: sys.path.insert(0, str(runtime))
        from authorized_supplement import request_enabled
        return request_enabled(request)
    if context.get('workflowId') in ALLOWED:
        return True
    import re
    workflow = context.get('workflowId')
    if workflow in ('daily-new-stores-opening-to-wechat', 'daily-store-task-completion-ops'):
        if request.get('groupName') != '上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰':
            return False
        items = request.get('items', [])
        event = context.get('eventId', '')
        if workflow == 'daily-new-stores-opening-to-wechat':
            return (re.fullmatch(r'\d{4}-\d{2}-\d{2}', event) is not None
                    and len(items) == 1 and items[0].get('itemId') == 'new-stores'
                    and items[0].get('type') == 'text' and bool(items[0].get('text')))
        return (re.fullmatch(r'\d{4}-\d{2}-\d{2}-taobao-store-task-detail', event) is not None
                and len(items) == 2
                and {i.get('itemId'): i.get('type') for i in items}
                    == {'store-task-detail': 'file', 'store-task-stats': 'image'}
                and all(str(i.get('path', '')).lower().endswith('.xlsx' if i['type'] == 'file' else '.png') for i in items))
    if context.get('workflowId') == 'meituan-customer-reply-daily':
        items = request.get('items', [])
        return (request.get('groupName') == '上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰'
                and len(items) == 1 and items[0].get('type') == 'file'
                and re.fullmatch(r'美团客户回复记录-\d{4}-\d{2}-\d{2}\.xlsx', Path(items[0].get('path', '')).name) is not None)
    # Merchant details and fixed half-hour notice retain their original scope.
    items = request.get('items', [])
    name = Path(context.get('eventId', '')).name
    return (context.get('workflowId') == 'merchants' and request.get('groupName') == '电销+直播攻坚组'
            and len(items) == 1 and items[0].get('type') == 'text' and bool(items[0].get('text'))
            and (re.fullmatch(r'[a-f0-9]{64}\.json', name) is not None
                 or (re.fullmatch(r'empty-\d{12}\.json', name) is not None
                     and items[0].get('text') == '当前无新增意向商家')))

def validate_response(task, reply):
    if reply.get('taskId') != task['taskId'] or reply.get('binding') != task['binding']:
        raise ValueError('ui-post-response-binding-mismatch')
    result = reply.get('result', {})
    if result.get('resolvedGroup') != task['request']['groupName']:
        raise ValueError('ui-post-response-target-mismatch')
    if task['stage'] == 'preflight':
        if result.get('ok') is not True or result.get('inputEmpty') is not True:
            raise ValueError('ui-post-preflight-not-verified')
    elif result.get('status') == 'verified':
        frames = result.get('observations', [])
        if (result.get('sendAttempts') != (0 if task['stage'] == 'readback' else 1) or result.get('sha256') != task['item']['sha256']
                or len(frames) != 2 or any(f.get('groupName') != task['request']['groupName']
                  or f.get('inputEmpty') is not True or f.get('newMessageVisible') is not True for f in frames)):
            raise ValueError('ui-post-send-evidence-invalid')
        kind = task['item']['type']
        if task.get('expectedPresentation') == 'inline-image':
            if any(f.get('presentation') != 'inline-image' or not str(f.get('visibleImageContent','')).strip() for f in frames):
                raise ValueError('ui-post-inline-image-not-proven')
        if kind == 'text' and any(f.get('visibleTextSha256') != task['item']['sha256'] for f in frames):
            raise ValueError('ui-post-text-readback-invalid')
        if kind == 'file':
            from file_size_policy import displayed_size_matches
            if (len({f.get('visibleFileSize') for f in frames}) != 1
                    or any(f.get('visibleFileName') != task['item']['name'] or not displayed_size_matches(task['item']['size'], f.get('visibleFileSize')) for f in frames)):
                raise ValueError('ui-post-file-card-invalid')
        level = {'text':'wecom-ui-tree-text', 'image':'wecom-ui-tree-image', 'file':'wecom-ui-tree-file-name-size'}[kind]
        result = result | {'verificationLevel': level,
                           'evidence': {'method':level,
                                        'resolvedGroup':task['request']['groupName'],'sha256':task['item']['sha256'],
                                        'observations':frames},
                           'transport':{'kind':kind,'sendAttempts':result['sendAttempts'],
                                        'sent':task['stage'] != 'readback','postSendInputCleared':[True,True],
                                        'stage':'post_send_verify'}}
    elif result.get('status') not in ('unknown', 'blocked'):
        raise ValueError('ui-post-outcome-invalid')
    return result

def exchange(stage, request, item=None, *, queue=QUEUE):
    if not enabled(request):
        raise ValueError('ui-post-workflow-not-enabled')
    queue.mkdir(parents=True, exist_ok=True, mode=0o700)
    task = {'taskId': str(uuid.uuid4()), 'stage': stage, 'request': request,
            'item': item, 'deadlineAt': request['context']['deadlineAt'] - 15}
    if item is not None:
        from presentation_policy import expected_presentation
        task['expectedPresentation'] = expected_presentation(item)
    task['binding'] = hashlib.sha256(json.dumps(task, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    folder = queue / task['taskId']; folder.mkdir(mode=0o700)
    atomic_json(folder / 'task.json', task)
    while time.time() < task['deadlineAt']:
        reply = folder / 'response.json'
        if reply.exists():
            return validate_response(task, json.loads(reply.read_text()))
        time.sleep(0.5)
    if stage == 'preflight':
        return {'ok': False, 'reason': 'ui-post-preflight-timeout', 'sendAttempts': 0}
    return {'status': 'unknown', 'sendAttempts': 1, 'reason': 'ui-post-result-timeout'}

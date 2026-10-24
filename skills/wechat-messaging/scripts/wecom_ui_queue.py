"""Original adapter transport handoff to the authorized visible-UI post."""
import hashlib
import json
import time
import uuid
from pathlib import Path
from ledger import atomic_json

QUEUE = Path('/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/wechat-messaging/.runtime/ui-post-queue')
ALLOWED = {'negative-reviews-summary'}

def enabled(request):
    context = request.get('context', {})
    if context.get('workflowId') in ALLOWED:
        return True
    # User-authorized half-hour empty notice only; merchant-detail migration is separate.
    import re
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
        if kind == 'text' and any(f.get('visibleTextSha256') != task['item']['sha256'] for f in frames):
            raise ValueError('ui-post-text-readback-invalid')
        result = result | {'verificationLevel': 'wecom-ui-tree-text' if kind == 'text' else 'wecom-ui-tree-image',
                           'evidence': {'method':'wecom-ui-tree-text' if kind == 'text' else 'wecom-ui-tree-image',
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

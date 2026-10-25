"""Read independently bound business facts without rewriting technical outcomes."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
GROUP = '上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰'
FLOW = 'daily-new-stores-decoration-audit-to-wechat'


def read_fact(flow, now=None):
    if flow != FLOW:
        return None
    now = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    day = now.strftime('%Y-%m-%d')
    audit_path = ROOT / 'runtime/state/delivery-audits' / (now.strftime('%Y%m%d') + '-decoration-observed.json')
    try:
        audit = json.loads(audit_path.read_text())
        folder = Path(audit['source']).resolve()
        queue = (ROOT / 'skills/wechat-messaging/.runtime/ui-post-queue').resolve()
        if folder.parent != queue or audit['date'] != day or audit['groupName'] != GROUP:
            return None
        originals = {}
        for name in ('task.json', 'response.json', 'send-intent.json'):
            raw = (folder / name).read_bytes()
            if hashlib.sha256(raw).hexdigest() != audit['sourceFiles'][name]:
                return None
            originals[name] = json.loads(raw)
        task, reply, intent = (originals[n] for n in ('task.json', 'response.json', 'send-intent.json'))
        binding = hashlib.sha256(json.dumps({k:v for k,v in task.items() if k != 'binding'},
                                            sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if not (binding == task['binding'] == reply['binding'] == intent['binding']
                and task['taskId'] == reply['taskId'] == intent['taskId'] == audit['taskId']
                and task['stage'] == 'send' and task['request']['groupName'] == GROUP):
            return None
        context = task['request']['context']
        item = task['item']
        result = reply['result']
        if not (context['workflowId'] == 'daily-new-stores-decoration-reminder'
                and context['eventId'].startswith(day + '-taobao-')
                and context['eventId'].endswith('-decoration-reminder')
                and item['type'] == 'text' and task['request']['items'] == [item]
                and result['status'] == 'unknown' and result['sendAttempts'] == 1
                and result['resolvedGroup'] == GROUP):
            return None
        sha = hashlib.sha256(item['text'].encode()).hexdigest()
        if not (sha == item['sha256'] == intent['sha256'] == result['sha256'] == audit['contentSha256']):
            return None
        frames = result['observations']
        if len(frames) != 2 or not (intent['at'] < frames[0]['observedAt'] < frames[1]['observedAt']):
            return None
        for frame in frames:
            observed = datetime.fromtimestamp(frame['observedAt'], ZoneInfo('Asia/Shanghai'))
            if not (frame['groupName'] == GROUP and frame['inputEmpty'] is True
                    and frame['newMessageVisible'] is True and frame['visibleText'] == item['text']
                    and frame['visibleTextSha256'] == sha and observed.strftime('%Y-%m-%d') == day
                    and observed.timestamp() <= now.timestamp()):
                return None
        return {'businessDelivered': True, 'taskId': task['taskId'], 'source': str(audit_path),
                'technicalStatusPreserved': 'unknown', 'newSendAttempts': 0,
                'observedAt': frames[-1]['observedAt']}
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return None

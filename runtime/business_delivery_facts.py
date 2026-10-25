"""Read independently bound business facts without rewriting technical outcomes."""
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
GROUP = '上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰'
FLOW = 'daily-new-stores-decoration-audit-to-wechat'
TAOBAO_IMAGES = 'daily-taobao-download-to-jinsha'


def _image_original(folder, name, sha, now):
    folder = Path(folder).resolve()
    if folder.parent != (ROOT / 'skills/wechat-messaging/.runtime/ui-post-queue').resolve():
        raise ValueError('image-task-out-of-scope')
    task = json.loads((folder/'task.json').read_text())
    reply = json.loads((folder/'response.json').read_text())
    intent = json.loads((folder/'send-intent.json').read_text())
    binding = hashlib.sha256(json.dumps({k:v for k,v in task.items() if k!='binding'},
                                        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    item = task['item']
    observed_day = datetime.fromtimestamp(intent['at'], ZoneInfo('Asia/Shanghai')).date()
    if not (task['stage']=='send' and task['request']['context']['workflowId']=='taobao-evidence'
            and task['request']['groupName']==GROUP and reply['result']['resolvedGroup']==GROUP
            and binding==task['binding']==reply['binding']==intent['binding']
            and task['taskId']==reply['taskId']==intent['taskId']
            and item['type']=='image' and item['name']==name
            and sha==item['sha256']==intent['sha256']
            and hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()==sha
            and reply['result']['status']=='unknown' and reply['result']['sendAttempts']==1
            and observed_day==now.date() and intent['at']<=now.timestamp()):
        raise ValueError('image-original-binding-invalid')
    return task


def _user_image_fact(now):
    day = now.strftime('%Y%m%d')
    path = ROOT / 'runtime/state/user-confirmed-deliveries' / (day+'-taobao-jinsha-second-image.json')
    try:
        acceptance = json.loads(path.read_text())
        if not (acceptance['source']=='explicit-user-confirmation' and acceptance['businessAccepted'] is True
                and acceptance['date']==now.strftime('%Y-%m-%d') and acceptance['groupName']==GROUP
                and acceptance['userQuote']=='能看到第二张图'):
            return None
        business_day = (now-timedelta(days=1)).strftime('%Y-%m-%d')
        prefix_path = ROOT / 'runtime/state' / ('taobao-image-user-prefix-'+business_day+'.json')
        if Path(acceptance['firstImageAcceptance']).resolve()!=prefix_path.resolve():
            return None
        prefix = json.loads(prefix_path.read_text())
        screenshot = Path(prefix['screenshot']).resolve()
        if not (prefix['source']=='explicit-user-business-confirmation'
                and prefix['businessDate']==business_day and prefix['groupName']==GROUP
                and prefix['confirmation']=='上传金鲨 这个 还差一个 图片 。'
                and screenshot.parent==(ROOT/'runtime/state/ui-user-evidence'/day).resolve()
                and hashlib.sha256(screenshot.read_bytes()).hexdigest()==prefix['screenshotSha256']):
            return None
        first = _image_original(prefix['taskDirectory'],'jinsha-store-final.png',prefix['sha256'],now)
        folder = ROOT/'skills/wechat-messaging/.runtime/ui-post-queue'/acceptance['taskId']
        second = _image_original(folder,'jinsha-review-final.png',acceptance['item']['sha256'],now)
        for name in ('task.json','response.json','send-intent.json'):
            if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=acceptance['sourceFiles'][name]:
                return None
        if second['binding']!=acceptance['binding'] or second['item']!=acceptance['item']:
            return None
        receipt = json.loads(Path(prefix['receiptFile']).read_text())
        evidence = receipt['evidenceManifest']
        if not (receipt['ok'] is True and receipt['phase']=='completed' and receipt['cleanupStatus']=='completed'
                and receipt['businessDate']==business_day and evidence['businessDate']==business_day
                and [i['sha256'] for i in evidence['images']]==[first['item']['sha256'],second['item']['sha256']]):
            return None
        return {'businessDelivered':True,'basis':'explicit-user-confirmation','source':str(path),
                'taskIds':[first['taskId'],second['taskId']], 'technicalStatusPreserved':'unknown',
                'newSendAttempts':0}
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return None


def read_fact(flow, now=None):
    now = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    if flow == TAOBAO_IMAGES:
        return _user_image_fact(now)
    if flow != FLOW:
        return None
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

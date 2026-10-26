"""Read independently bound business facts without rewriting technical outcomes."""
import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
GROUP = '上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰'
FLOW = 'daily-new-stores-decoration-audit-to-wechat'
TAOBAO_IMAGES = 'daily-taobao-download-to-jinsha'
SERVICE_RANKING = 'daily-service-market-ranking-to-wechat'
SERVICE_RANKING_QUOTE = '今天这个已经发了就算值班过了，今天的 日报台账里应该有它，明天继续'
CLOSING = {'meituan-waimai-negative-review-appeals-11': ('meituan', 'meituan-waimai-appeals', '美团外卖'),
           'taobao-flash-sale-negative-review-appeals': ('taobao', 'taobao-flash-appeals', '淘宝闪购')}


def _image_original(folder, name, sha, now, workflow='taobao-evidence'):
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
    if not (task['stage']=='send' and task['request']['context']['workflowId']==workflow
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


def _closing_fact(flow, now):
    platform, route, label = CLOSING[flow]
    day=now.strftime('%Y-%m-%d');business_day=(now-timedelta(days=1)).strftime('%Y-%m-%d')
    path=ROOT/'runtime/state/user-confirmed-deliveries'/(now.strftime('%Y%m%d')+'-appeal-closing-images.json')
    try:
        acceptance=json.loads(path.read_text())
        if not (acceptance['source']=='explicit-user-confirmation' and acceptance['businessAccepted'] is True
                and acceptance['date']==day and acceptance['groupName']==GROUP
                and acceptance['userQuote']=='两张图都能看到'):
            return None
        proof=acceptance['platforms'][platform]
        record_path=Path(proof['runRecord']).resolve();log_path=Path(proof['runLog']).resolve()
        history=(ROOT/'runtime/run_history'/day).resolve()
        if record_path.parent!=history or log_path.parent!=history:
            return None
        if (hashlib.sha256(record_path.read_bytes()).hexdigest()!=proof['runRecordSha256']
                or hashlib.sha256(log_path.read_bytes()).hexdigest()!=proof['runLogSha256']):
            return None
        record=json.loads(record_path.read_text())
        started=datetime.fromisoformat(record['started_at'])
        if (record['skill']!=flow or started.strftime('%Y-%m-%d')!=day
                or (started.hour,started.minute)<(18,30) or str(log_path) not in record['logs']):
            return None
        receipts=[]
        for line in log_path.read_text().splitlines():
            try: receipts.append(json.loads(line))
            except ValueError: continue
        closing=next(r for r in reversed(receipts) if r.get('platform')==platform and r.get('slot')=='18:30')
        stages={s['stage']:s['receipt'] for s in closing['results']}
        if not (stages['appeal']['ok'] is True and stages['build']['ok'] is True
                and stages['appeal']['businessDate']==business_day and stages['build']['businessDate']==business_day
                and not stages['appeal'].get('unknown') and not stages['appeal'].get('blocked')):
            return None
        queue=ROOT/'skills/wechat-messaging/.runtime/ui-post-queue'
        for kind in ('file','image'):
            folder=queue/proof[kind]['taskId']
            for name in ('task.json','response.json','send-intent.json'):
                if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=proof[kind]['sources'][name]:
                    return None
        image=_image_original(queue/proof['image']['taskId'],label+'差评申诉台账-'+business_day+'.png',
                              proof['image']['sha256'],now,workflow=route+'-summary')
        folder=queue/proof['file']['taskId'];task=json.loads((folder/'task.json').read_text())
        reply=json.loads((folder/'response.json').read_text());intent=json.loads((folder/'send-intent.json').read_text())
        binding=hashlib.sha256(json.dumps({k:v for k,v in task.items() if k!='binding'},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if not (task['stage']=='send' and task['request']['context']['workflowId']==route
                and task['request']['groupName']==GROUP and task['item']['type']=='file'
                and task['item']['name']==label+'差评申诉汇总-'+business_day+'.xlsx'
                and binding==task['binding']==reply['binding']==intent['binding']
                and task['taskId']==reply['taskId']==intent['taskId']
                and task['item']['sha256']==proof['file']['sha256']==intent['sha256']
                and hashlib.sha256(Path(task['item']['path']).read_bytes()).hexdigest()==task['item']['sha256']
                and reply['result']['status']=='verified' and reply['result']['sendAttempts']==1):
            return None
        scripts=ROOT/'skills/wechat-messaging/scripts'
        if str(scripts) not in sys.path:sys.path.insert(0,str(scripts))
        from wecom_ui_queue import validate_response
        validate_response(task,reply)
        return {'businessDelivered':True,'basis':'explicit-user-confirmation','source':str(path),
                'taskIds':[task['taskId'],image['taskId']],'technicalStatusPreserved':'unknown','newSendAttempts':0}
    except (OSError, ValueError, KeyError, TypeError, IndexError, StopIteration):
        return None


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


def _service_ranking_fact(now):
    day = now.strftime('%Y-%m-%d')
    path = ROOT/'runtime/state/user-confirmed-deliveries'/(now.strftime('%Y%m%d')+'-service-market-ranking.json')
    base = ROOT/'skills/workflows/daily-service-market-ranking-to-wechat/.runtime/days'/day
    try:
        acceptance = json.loads(path.read_text())
        if not (acceptance['source']=='explicit-user-confirmation' and acceptance['businessAccepted'] is True
                and acceptance['date']==day and acceptance['groupName']==GROUP
                and acceptance['userQuote']==SERVICE_RANKING_QUOTE):
            return None
        queue = ROOT/'skills/wechat-messaging/.runtime/ui-post-queue'
        folder = queue/acceptance['taskId']
        if folder.resolve().parent != queue.resolve():
            return None
        for name in ('task.json','response.json','send-intent.json'):
            if hashlib.sha256((folder/name).read_bytes()).hexdigest()!=acceptance['sourceFiles'][name]:
                return None
        for name in ('frozen.json','delivery.json'):
            if hashlib.sha256((base/name).read_bytes()).hexdigest()!=acceptance['originalFiles'][name]:
                return None
        frozen = json.loads((base/'frozen.json').read_text())
        marker = json.loads((base/'delivery.json').read_text())
        item = frozen['item']
        name = day+'-服务市场排名与考核指标.png'
        task = _image_original(folder,name,item['sha256'],now,workflow='daily-service-market-ranking-ops')
        result = json.loads((folder/'response.json').read_text())['result']
        collected = datetime.fromisoformat(frozen['collection']['collectedAt'].replace('Z','+00:00'))
        if not (frozen['day']==day and frozen['collection']['ok'] is True
                and frozen['collection']['browserPort']==9231
                and collected.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')==day
                and len(frozen['collection']['metrics'])>=8
                and item==task['item'] and task['request']['items']==[item]
                and Path(item['path']).resolve()==(base/name).resolve()
                and task['request']['context']['eventId']==day+'-service-market-ranking'
                and marker['eventId']==day+'-service-market-ranking' and marker['groupName']==GROUP
                and marker['state']=='unknown' and marker['sendAttempts']==1 and marker['sha256']==item['sha256']
                and result['backend']=='system-events-ui-tree' and result['inputEmpty'] is True):
            return None
        return {'businessDelivered':True,'basis':'explicit-user-confirmation','source':str(path),
                'taskIds':[task['taskId']],'technicalStatusPreserved':'unknown','newSendAttempts':0}
    except (OSError,ValueError,KeyError,TypeError,IndexError):
        return None


def read_fact(flow, now=None):
    now = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    if flow == SERVICE_RANKING:
        return _service_ranking_fact(now)
    if flow == TAOBAO_IMAGES:
        return _user_image_fact(now)
    if flow in CLOSING:
        return _closing_fact(flow, now)
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

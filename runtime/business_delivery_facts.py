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
TAOBAO_CLOSING_QUOTE = '美团外卖差评申诉的台账 图片 没见发出来 ，淘宝闪购的 已经发了'


def _image_original(folder, name, sha, now, workflow='taobao-evidence', allowed_statuses=('unknown',)):
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
            and reply['result']['status'] in allowed_statuses and reply['result']['sendAttempts']==1
            and observed_day==now.date() and intent['at']<=now.timestamp()):
        raise ValueError('image-original-binding-invalid')
    return task


def closing_stages_valid(closing, business_day, run_day):
    """Read the actual closing contract; never invent an absent appeal stage."""
    try:
        entries = closing['results']
        names = [entry['stage'] for entry in entries]
        modern = run_day >= '2026-10-27'
        if names != (['build', 'deliver'] if modern else ['appeal', 'build', 'deliver']):
            return False
        stages = {entry['stage']: entry['receipt'] for entry in entries}
        build = stages['build']
        if build.get('ok') is not True or build.get('businessDate') != business_day:
            return False
        if modern:
            count = build.get('recordCount')
            return type(count) is int and count > 0 and build.get('counts', {}).get('全部') == count
        appeal = stages['appeal']
        return (appeal.get('ok') is True and appeal.get('businessDate') == business_day
                and not appeal.get('unknown') and not appeal.get('blocked'))
    except (KeyError, TypeError, AttributeError):
        return False


def closing_confirmation_valid(acceptance, platform, now):
    """Scope explicit business acceptance without promoting technical receipts."""
    try:
        day = now.strftime('%Y-%m-%d')
        if not (acceptance['source'] == 'explicit-user-confirmation'
                and acceptance['businessAccepted'] is True
                and acceptance['date'] == day and acceptance['groupName'] == GROUP):
            return False
        if acceptance['userQuote'] == '两张图都能看到':
            return True
        if not (platform == 'taobao' and acceptance['userQuote'] == TAOBAO_CLOSING_QUOTE
                and acceptance.get('confirmedPlatforms') == ['taobao']
                and set(acceptance['platforms']) == {'taobao'}):
            return False
        source = ROOT/'runtime/state/user-confirmed-deliveries'/(now.strftime('%Y%m%d')+'-taobao-appeals-summary-user-visible.json')
        if hashlib.sha256(source.read_bytes()).hexdigest() != acceptance['userConfirmationSha256']:
            return False
        evidence = json.loads(source.read_text())
        stamp = datetime.fromisoformat(evidence['at'])
        return (stamp.strftime('%Y-%m-%d') == day
                and stamp.replace(tzinfo=now.tzinfo) <= now
                and evidence['userQuote'] == TAOBAO_CLOSING_QUOTE
                and evidence['flow'] == 'taobao-flash-sale-negative-review-appeals'
                and evidence['businessDate'] == (now-timedelta(days=1)).strftime('%Y-%m-%d'))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _closing_fact(flow, now):
    platform, route, label = CLOSING[flow]
    day=now.strftime('%Y-%m-%d');business_day=(now-timedelta(days=1)).strftime('%Y-%m-%d')
    path=ROOT/'runtime/state/user-confirmed-deliveries'/(now.strftime('%Y%m%d')+'-appeal-closing-images.json')
    if not path.exists() and platform == 'taobao':
        path=path.with_name(now.strftime('%Y%m%d')+'-appeal-closing-taobao.json')
    try:
        acceptance=json.loads(path.read_text())
        if not closing_confirmation_valid(acceptance, platform, now):
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
        if not closing_stages_valid(closing, business_day, day):
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


# One dated user acceptance, separate from transport receipts and future duties.
EXECUTED_IMAGE_FLOWS = {
    'daily-top10-to-wechat-group': ('top10', 1),
    'daily-negative-reviews': ('negative-reviews-summary', 1),
    'daily-store-task-completion-ops-to-wechat': ('daily-store-task-completion-ops', 1),
    'contract-termination-applications-screenshot': ('contract-termination-ops', 1),
    'daily-taobao-download-to-jinsha': ('taobao-evidence', 2),
    'daily-meituan-income-top10-to-wechat': ('daily-meituan-income-top10-ops', 1),
}
EXECUTED_IMAGE_QUOTES = [
    '今天所有已经执行的任务流的图片提交 我都看了没有问题 只是有个通病；回执待确认/unknow 等',
    '是的 今天已经执行的任务流 都执行成功了 没有 遗漏和错过的',
]
EXECUTED_IMAGE_QUOTE_20261027 = '这些图片都有一次提交记录，卡在内容回读，我看到都发送成功了，但是你工作流没拿到回执 事情已经发生了你看如何完善维护，不过 工作流确实执行成功了 可以发台账'


def _request_image_matches(candidate, item):
    if (candidate.get('type') != 'image' or candidate.get('itemId') != item.get('itemId')
            or candidate.get('name', Path(candidate.get('path', '')).name) != item['name']):
        return False
    if candidate.get('sha256') is not None:
        return (candidate['sha256'] == item['sha256']
                and candidate.get('size', item.get('size')) == item.get('size'))
    source = Path(candidate.get('path', ''))
    return source.is_file() and hashlib.sha256(source.read_bytes()).hexdigest() == item['sha256']


def _executed_images_user_fact(flow, now):
    if now.tzinfo is None:
        now = now.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
    day = now.strftime('%Y-%m-%d')
    current = day == '2026-10-27'
    flows = dict(EXECUTED_IMAGE_FLOWS)
    if current:
        flows.update({SERVICE_RANKING: ('daily-service-market-ranking-ops', 1),
                      'taobao-flash-sale-negative-review-appeals': ('taobao-flash-appeals-summary', 1),
                      'meituan-waimai-negative-review-appeals-11': ('meituan-waimai-appeals-summary', 1)})
    if flow not in flows or day not in ('2026-10-26', '2026-10-27'):
        return None
    filename = '20261027-executed-image-submissions-user-confirmed.json' if current else '20261026-executed-image-submissions-173035.json'
    path = ROOT/'runtime/state/user-confirmed-deliveries'/filename
    try:
        acceptance = json.loads(path.read_text())
        cutoff = datetime.fromisoformat(acceptance['recordedAt'])
        if not (acceptance['source'] == 'explicit-user-confirmation'
                and acceptance['businessAccepted'] is True and acceptance['date'] == day
                and acceptance['userQuotes'] == ([EXECUTED_IMAGE_QUOTE_20261027] if current else EXECUTED_IMAGE_QUOTES)
                and cutoff.date() == now.date() and cutoff <= now):
            return None
        route, count = flows[flow]
        selected = [i for i in acceptance['items'] if i['workflowId'] == route]
        if len(selected) != count or len({i['taskId'] for i in selected}) != count:
            return None
        if current:
            expected_names = {
                'top10': {'2026-10-26_top10seller.png'},
                'negative-reviews-summary': {'差评分析长图_2026-10-26_2026-10-26.jpg'},
                'daily-store-task-completion-ops': {'2026-10-27运营-店铺经营任务完成率.png'},
                'contract-termination-ops': {'2026-10-27_合同解约申请_处理中_p1.png'},
                'taobao-evidence': {'jinsha-store-final.png', 'jinsha-review-final.png'},
                'daily-meituan-income-top10-ops': {'2026-10-26-美团外卖门店收入top10.png'},
                'daily-service-market-ranking-ops': {'2026-10-27-服务市场排名与考核指标.png'},
                'taobao-flash-appeals-summary': {'淘宝闪购差评申诉台账-2026-10-26.png'},
                'meituan-waimai-appeals-summary': {'美团外卖差评申诉台账-2026-10-26.png'},
            }
            if {i['name'] for i in selected} != expected_names[route]:
                return None
        queue = ROOT/'skills/wechat-messaging/.runtime/ui-post-queue'
        for proof in selected:
            folder = queue/proof['taskId']
            for name in ('task.json', 'response.json', 'send-intent.json'):
                if hashlib.sha256((folder/name).read_bytes()).hexdigest() != proof['sources'][name]:
                    return None
            task = _image_original(folder, proof['name'], proof['sha256'], cutoff, workflow=route)
            result = json.loads((folder/'response.json').read_text())['result']
            if not (proof['groupName'] == GROUP
                    and task['request']['context']['eventId'] == proof['eventId']
                    and sum(_request_image_matches(candidate, task['item']) for candidate in task['request']['items']) == 1
                    and result['backend'] == 'system-events-ui-tree' and result['inputEmpty'] is True):
                return None
        if flow == 'daily-meituan-income-top10-to-wechat':
            base = ROOT/'skills/workflows/daily-meituan-income-top10-to-wechat/.runtime/days'/day
            marker = json.loads((base/'delivery.json').read_text())
            frozen = json.loads((base/'frozen.json').read_text())
            label = marker['deliveries'][0]
            if not (marker['state'] == 'unknown' and marker['eventId'] == day+'-meituan-income-top10'
                    and marker['groupName'] == GROUP and marker['sha256'] == selected[0]['sha256']
                    and frozen['day'] == day and frozen['collection']['dataDate'] == (now-timedelta(days=1)).strftime('%Y-%m-%d')
                    and frozen['item'] == task['item'] and len(task['request']['items']) == 2
                    and task['request']['items'][0]['text'] == '美团外卖门店收入top10'
                    and label['itemId'] == 'meituan-income-label' and label['receipt']['status'] == 'verified'):
                return None
        return {'businessDelivered': True, 'basis': 'explicit-user-confirmation', 'source': str(path),
                'taskIds': [i['taskId'] for i in selected], 'technicalStatusPreserved': 'unknown',
                'newSendAttempts': 0}
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return None


SUBMITTED_IMAGE_POLICY_QUOTE='后续不需要人工确认，你发送后 可能没有回执 你仅仅备注下即可  因为长期的观察发现 都是执行成功的，你是没解决回执问题 不代表业务没走成功 ，是给客户看的台账'


def _standing_submitted_image_fact(flow, now):
    """Business policy for original single submissions; never changes transport records."""
    if now.tzinfo is None:
        now=now.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
    else:
        now=now.astimezone(ZoneInfo('Asia/Shanghai'))
    routes=dict(EXECUTED_IMAGE_FLOWS)
    routes.update({SERVICE_RANKING:('daily-service-market-ranking-ops',1),
                   'taobao-flash-sale-negative-review-appeals':('taobao-flash-appeals-summary',1),
                   'meituan-waimai-negative-review-appeals-11':('meituan-waimai-appeals-summary',1)})
    if flow not in routes:return None
    policy_path=ROOT/'runtime/policies/submitted-image-business-policy.json'
    try:
        policy=json.loads(policy_path.read_text())
        effective=datetime.fromisoformat(policy['recordedAt'])
        if not (policy['source']=='explicit-user-standing-instruction' and policy['userQuote']==SUBMITTED_IMAGE_POLICY_QUOTE
                and policy['businessCompleteOnBoundSingleSubmission'] is True and policy['preserveTechnicalStatus'] is True
                and policy['noResend'] is True and policy['clientTechnicalDetails'] is False
                and effective.tzinfo is not None and effective<=now and now.date()>=effective.astimezone(now.tzinfo).date()):return None
        route,count=routes[flow];day=now.strftime('%Y-%m-%d');previous=(now-timedelta(days=1)).strftime('%Y-%m-%d')
        names={
            'top10':{previous+'_top10seller.png'},
            'negative-reviews-summary':{f'差评分析长图_{previous}_{previous}.jpg'},
            'daily-store-task-completion-ops':{day+'运营-店铺经营任务完成率.png'},
            'contract-termination-ops':{day+'_合同解约申请_处理中_p1.png'},
            'taobao-evidence':{'jinsha-store-final.png','jinsha-review-final.png'},
            'daily-meituan-income-top10-ops':{previous+'-美团外卖门店收入top10.png'},
            'daily-service-market-ranking-ops':{day+'-服务市场排名与考核指标.png'},
            'taobao-flash-appeals-summary':{'淘宝闪购差评申诉台账-'+previous+'.png'},
            'meituan-waimai-appeals-summary':{'美团外卖差评申诉台账-'+previous+'.png'},
        }[route]
        queue=ROOT/'skills/wechat-messaging/.runtime/ui-post-queue';selected=[];statuses=[]
        for task_file in queue.glob('*/task.json'):
            try:
                intent_file=task_file.parent/'send-intent.json';reply_file=task_file.parent/'response.json'
                if not intent_file.is_file() or not reply_file.is_file():continue
                intent=json.loads(intent_file.read_text());stamp=intent.get('at')
                if type(stamp) not in (int,float) or datetime.fromtimestamp(stamp,now.tzinfo).date()!=now.date():continue
                task=json.loads(task_file.read_text())
            except (OSError,ValueError,KeyError,TypeError):continue
            if task.get('stage')!='send' or task.get('request',{}).get('context',{}).get('workflowId')!=route or task.get('item',{}).get('type')!='image':continue
            try:
                result=json.loads(reply_file.read_text())['result']
                if type(result.get('sendAttempts')) is not int:return None
                if result['sendAttempts']==0:continue
                item=task['item'];original=_image_original(task_file.parent,item['name'],item['sha256'],now,workflow=route,allowed_statuses=('unknown','verified'))
                if result.get('backend')!='system-events-ui-tree':return None
                if result['status']=='unknown' and result.get('inputEmpty') is not True:return None
                if result['status']=='verified' and (result.get('sha256')!=item['sha256'] or len(result.get('observations',[]))!=2
                    or any(o.get('groupName')!=GROUP or o.get('inputEmpty') is not True for o in result['observations'])):return None
                if sum(_request_image_matches(candidate,item) for candidate in original['request']['items'])!=1:return None
                selected.append(original)
                statuses.append(result['status'])
            except (OSError,ValueError,KeyError,TypeError,IndexError):
                return None
        if len(selected)!=count or len({t['taskId'] for t in selected})!=count or {t['item']['name'] for t in selected}!=names:return None
        if flow=='daily-meituan-income-top10-to-wechat':
            base=ROOT/'skills/workflows/daily-meituan-income-top10-to-wechat/.runtime/days'/day
            marker=json.loads((base/'delivery.json').read_text());frozen=json.loads((base/'frozen.json').read_text());task=selected[0]
            if not (marker['state']=='unknown' and marker['eventId']==day+'-meituan-income-top10' and marker['groupName']==GROUP
                    and marker['sha256']==task['item']['sha256'] and frozen['day']==day and frozen['collection']['dataDate']==previous
                    and frozen['item']==task['item'] and len(task['request']['items'])==2
                    and task['request']['items'][0]['text']=='美团外卖门店收入top10'
                    and marker['deliveries'][0]['itemId']=='meituan-income-label' and marker['deliveries'][0]['receipt']['status']=='verified'):return None
        return {'businessDelivered':True,'basis':'bound-single-submission-standing-user-policy','source':str(policy_path),
                'taskIds':[t['taskId']for t in selected],'technicalStatusPreserved':'unknown' if 'unknown' in statuses else 'verified','newSendAttempts':0,
                'humanConfirmationRequired':False,'internalNote':'原图片已单次提交，内容回执待核；不重发'}
    except (OSError,ValueError,KeyError,TypeError,IndexError):return None


def read_fact(flow, now=None):
    now = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    submitted=_standing_submitted_image_fact(flow,now)
    if submitted:return submitted
    accepted = _executed_images_user_fact(flow, now)
    if accepted:
        return accepted
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


def read_execution_note(flow, now=None):
    if flow != 'daily-quality-products-optimization':
        return None
    now = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    day = now.strftime('%Y-%m-%d')
    base = ROOT/'skills/workflows/daily-quality-products-optimization/.runtime/days'/day
    try:
        proof = json.loads((base/'completion.json').read_text())
        delivery = json.loads((base/'delivery.json').read_text())
        count = proof.get('attemptedUnconfirmed', 0)
        if not (proof['day'] == day and proof['workflowId'] == flow and proof['groupName'] == GROUP
                and type(count) is int and 0 < count <= proof['handled']
                and delivery['state'] == 'verified' and len(delivery['deliveries']) == 2
                and all(item['receipt']['status'] == 'verified' for item in delivery['deliveries'])):
            return None
        return f'已执行，{count}家结果待确认'
    except (OSError,ValueError,KeyError,TypeError):
        return None

"""UI transport scope for existing registered business contracts; no effects."""
from pathlib import Path

WORKFLOWS = {'negative-reviews', 'top10', 'jinsha-reports', 'negative-feedback-appeals', 'taobao-evidence',
             'taobao-flash-appeals', 'meituan-waimai-appeals',
             'taobao-flash-appeals-summary', 'meituan-waimai-appeals-summary'}
GROUP = '上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰'
DIRECT = {
    'daily-new-stores-activity-reminder': ('missing-activity', 'text', r'taobao-\d+-activity-reminder'),
    'daily-new-stores-decoration-reminder': ('missing-decoration', 'text', r'taobao-\d+-decoration-reminder'),
    'daily-store-basic-diagnosis-ops': ('store-basic-diagnosis', 'file', 'store-basic-diagnosis-ops'),
    'daily-new-stores-not-nourished-ops': ('not-nourished-ops', 'file', 'taobao-not-nourished-ops'),
}

def service_ranking_allowed(request, *, root=None, day=None):
    import hashlib
    import re
    from datetime import datetime
    from zoneinfo import ZoneInfo
    root = Path(root) if root is not None else Path(__file__).resolve().parents[3]
    day = day or datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
    context = request.get('context', {})
    items = request.get('items', [])
    if (request.get('groupName') != GROUP or context.get('workflowId') != 'daily-service-market-ranking-ops'
            or context.get('eventId') != day + '-service-market-ranking' or len(items) != 1
            or context.get('accountAlias') != 'main-wechat' or context.get('channel') != 'desktop'):
        return False
    item = items[0]
    expected = root / 'skills/workflows/daily-service-market-ranking-to-wechat/.runtime/days' / day / (day + '-服务市场排名与考核指标.png')
    try:
        return (item.get('itemId') == 'service-ranking' and item.get('type') == 'image'
                and Path(item.get('path', '')).resolve() == expected.resolve()
                and item.get('name') == expected.name and expected.is_file()
                and item.get('size') == expected.stat().st_size
                and item.get('sha256') == hashlib.sha256(expected.read_bytes()).hexdigest())
    except (OSError, ValueError, TypeError):
        return False


def top10_label_allowed(request, *, day=None):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    day=day or (datetime.now(ZoneInfo('Asia/Shanghai')).date()-timedelta(days=1)).isoformat()
    context=request.get('context',{});items=request.get('items',[])
    return (request.get('groupName')==GROUP and context.get('workflowId')=='top10-income-label'
            and context.get('eventId')==day+'-taobao-income-top10-label'
            and context.get('accountAlias')=='main-wechat' and context.get('channel')=='desktop'
            and len(items)==1 and items[0].get('itemId')=='taobao-income-label'
            and items[0].get('type')=='text' and items[0].get('text')=='淘宝闪购门店收入top10')


def meituan_income_allowed(request, *, root=None, day=None):
    import hashlib
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    root=Path(root) if root is not None else Path(__file__).resolve().parents[3]
    day=day or datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
    data_date=(datetime.fromisoformat(day).date()-timedelta(days=1)).isoformat()
    context=request.get('context',{});items=request.get('items',[])
    if not (request.get('groupName')==GROUP and context.get('workflowId')=='daily-meituan-income-top10-ops'
            and context.get('eventId')==day+'-meituan-income-top10' and context.get('accountAlias')=='main-wechat'
            and context.get('channel')=='desktop' and len(items)==2):
        return False
    label,image=items
    expected=root/'skills/workflows/daily-meituan-income-top10-to-wechat/.runtime/days'/day/(data_date+'-美团外卖门店收入top10.png')
    try:
        return (label.get('itemId')=='meituan-income-label' and label.get('type')=='text'
                and label.get('text')=='美团外卖门店收入top10'
                and label.get('sha256')==hashlib.sha256('美团外卖门店收入top10'.encode()).hexdigest()
                and image.get('itemId')=='meituan-income-top10' and image.get('type')=='image'
                and Path(image.get('path','')).resolve()==expected.resolve() and image.get('name')==expected.name
                and image.get('size')==expected.stat().st_size
                and image.get('sha256')==hashlib.sha256(expected.read_bytes()).hexdigest())
    except (OSError,ValueError,TypeError):
        return False


def quality_optimization_allowed(request, *, root=None, day=None):
    import hashlib
    import json
    from datetime import datetime
    from zoneinfo import ZoneInfo
    root=Path(root) if root is not None else Path(__file__).resolve().parents[3]
    day=day or datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
    context=request.get('context',{});items=request.get('items',[])
    if not (request.get('groupName')==GROUP and context.get('workflowId')=='daily-quality-products-optimization'
            and context.get('eventId')==day+'-quality-optimization-completed' and context.get('accountAlias')=='main-wechat'
            and context.get('channel')=='desktop' and len(items)==2):return False
    folder=root/'skills/workflows/daily-quality-products-optimization/.runtime/days'/day
    try:
        proof=json.loads((folder/'completion.json').read_text());raw=(folder/'state.json').read_bytes();state=json.loads(raw);report=json.loads((folder/'report.json').read_text())
        stores=state['stores'];optimized=[s for s in stores if s['state']=='completed'];count=len(optimized);text=f'淘宝闪购 优质商品率低 店铺全部店铺优化完成 （今日执行了 {count} 家）'
        if not (proof['day']==state['day']==day and proof['workflowId']==state['workflowId']=='daily-quality-products-optimization'
                and proof['accountName']=='zhangyanru188' and state['accountLabel']=='zhangyanru188:全部门店'
                and proof['groupName']==GROUP and proof['stateSha256']==hashlib.sha256(raw).hexdigest()
                and type(proof['completed']) is int and proof['completed']==count and state['scopeFinished'] is True
                and proof['completedShopIds']==[s['shopId'] for s in optimized]
                and proof['handledShopIds']==[s['shopId'] for s in stores] and len(set(proof['handledShopIds']))==len(stores)
                and all(s['state'] in ('completed','checked_no_action') for s in stores) and proof['text']==text):return False
        for store in optimized:
            if not all(store.get('operation',{}).get(k) is True for k in ['confirmed','popoverClosed','uiStable']):return False
        file,label=items;expected=folder/(day+'淘宝闪购商品整改执行台账.xlsx')
        if not (file.get('itemId')=='quality-execution-ledger' and file.get('type')=='file' and Path(file.get('path','')).resolve()==expected.resolve()
                and file.get('name')==expected.name and file.get('sha256')==hashlib.sha256(expected.read_bytes()).hexdigest()==report['sha256']
                and file.get('size')==expected.stat().st_size==report['size'] and report['rows']==len(stores)
                and report['sourceSha256']==hashlib.sha256((folder/'completion.json').read_bytes()).hexdigest()):return False
        return (label.get('itemId')=='quality-optimization-completed' and label.get('type')=='text'
                and label.get('text')==text and label.get('sha256')==hashlib.sha256(text.encode()).hexdigest())
    except (OSError,ValueError,KeyError,TypeError):return False


def allowed_direct(request):
    if request.get('context',{}).get('workflowId')=='daily-quality-products-optimization':
        return quality_optimization_allowed(request)
    if request.get('context',{}).get('workflowId')=='daily-meituan-income-top10-ops':
        return meituan_income_allowed(request)
    if request.get('context', {}).get('workflowId') == 'top10-income-label':
        return top10_label_allowed(request)
    if request.get('context', {}).get('workflowId') == 'daily-service-market-ranking-ops':
        return service_ranking_allowed(request)
    import re
    context = request.get('context', {})
    scope = DIRECT.get(context.get('workflowId'))
    if scope is None or request.get('groupName') != GROUP:
        return False
    item_id, kind, event_suffix = scope
    items = request.get('items', [])
    if len(items) != 1 or re.fullmatch(r'\d{4}-\d{2}-\d{2}-' + event_suffix, context.get('eventId', '')) is None:
        return False
    item = items[0]
    if item.get('itemId') != item_id or item.get('type') != kind:
        return False
    return bool(str(item.get('text', '')).strip()) if kind == 'text' else str(item.get('path', '')).lower().endswith('.xlsx')

def allowed(request):
    workflow = request.get('context', {}).get('workflowId')
    if workflow not in WORKFLOWS:
        return False
    from workflow_bridge import REGISTRY
    group, kind, count, _, ledger = REGISTRY[workflow]
    if request.get('groupName') != group or group != GROUP:
        return False
    items = request.get('items', [])
    counts = range(count[0], count[1]+1) if isinstance(count, tuple) else (count,)
    if len(items) not in counts:
        return False
    event = Path(request.get('context', {}).get('eventId', ''))
    if not event.is_absolute() or event.parent.resolve() != ledger.resolve() or event.suffix != '.json':
        return False
    suffix = '.png' if kind == 'image' else '.xlsx'
    return all(item.get('type') == kind and str(item.get('path', '')).lower().endswith(suffix) for item in items)

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

def allowed_direct(request):
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

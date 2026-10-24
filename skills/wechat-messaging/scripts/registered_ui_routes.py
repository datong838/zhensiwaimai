"""UI transport scope for existing registered business contracts; no effects."""
from pathlib import Path

WORKFLOWS = {'top10', 'jinsha-reports', 'negative-feedback-appeals', 'taobao-evidence'}
GROUP = '上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰'

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

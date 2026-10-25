"""User-authorized native UI acceptance, bound to one synthetic test batch."""
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
GROUP = '临时测试群请忽略 💰发财精英荟💰'
WORKFLOW_PREFIX = 'native-ui-acceptance-'


def binding_for_day(day):
    iso_day = day.isoformat()
    return (ROOT / f'runtime/state/native-ui-acceptance-{iso_day}',
            WORKFLOW_PREFIX + iso_day.replace('-', ''))


def request_enabled(request, *, now=None):
    try:
        current = now or datetime.now(ZoneInfo('Asia/Shanghai'))
        scope, workflow = binding_for_day(current.astimezone(ZoneInfo('Asia/Shanghai')).date())
        manifest = json.loads((scope / 'manifest.json').read_text(encoding='utf-8'))
        return (request == manifest['request'] and request['groupName'] == GROUP
                and request['context']['workflowId'] == workflow
                and manifest['grant']['groupName'] == GROUP)
    except (OSError, ValueError, KeyError):
        return False


def execute():
    sys.path.insert(0, str(ROOT / 'skills/wechat-messaging/scripts'))
    from executor import deliver
    from wecom_adapter import WeComAdapter
    from ledger import atomic_json
    scope, _ = binding_for_day(datetime.now(ZoneInfo('Asia/Shanghai')).date())
    data = json.loads((scope / 'manifest.json').read_text(encoding='utf-8'))
    if not request_enabled(data['request']):
        raise ValueError('native-acceptance-scope-invalid')
    result = deliver(data['request'], data['grant'], scope / 'delivery-ledger', WeComAdapter())
    atomic_json(scope / 'delivery-receipt.json', result)
    return result


if __name__ == '__main__':
    print(json.dumps(execute(), ensure_ascii=False))

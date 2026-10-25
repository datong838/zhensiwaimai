"""User-authorized native UI acceptance, bound to one synthetic test batch."""
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
SCOPE = ROOT / 'runtime/state/native-ui-acceptance-20261025'
WORKFLOW = 'native-ui-acceptance-20261025'
GROUP = '临时测试群请忽略 💰发财精英荟💰'


def request_enabled(request):
    try:
        manifest = json.loads((SCOPE / 'manifest.json').read_text(encoding='utf-8'))
        return (datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat() == '2026-10-25'
                and request == manifest['request'] and request['groupName'] == GROUP
                and request['context']['workflowId'] == WORKFLOW
                and manifest['grant']['groupName'] == GROUP)
    except (OSError, ValueError, KeyError):
        return False


def execute():
    sys.path.insert(0, str(ROOT / 'skills/wechat-messaging/scripts'))
    from executor import deliver
    from wecom_adapter import WeComAdapter
    from ledger import atomic_json
    data = json.loads((SCOPE / 'manifest.json').read_text(encoding='utf-8'))
    if not request_enabled(data['request']):
        raise ValueError('native-acceptance-scope-invalid')
    result = deliver(data['request'], data['grant'], SCOPE / 'delivery-ledger', WeComAdapter())
    atomic_json(SCOPE / 'delivery-receipt.json', result)
    return result


if __name__ == '__main__':
    print(json.dumps(execute(), ensure_ascii=False))

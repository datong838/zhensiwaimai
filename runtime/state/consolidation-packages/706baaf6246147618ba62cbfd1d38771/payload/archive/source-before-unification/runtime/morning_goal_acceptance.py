"""Explicit one-off morning-chain acceptance using the original UI delivery engine."""
import json
import os
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
SCOPE=ROOT/'runtime/state/morning-goal-test-20261024-2120'
WORKFLOW='morning-goal-test-20261024-2120'
GROUP='临时测试群请忽略 💰发财精英荟💰'
def request_enabled(request):
    try:
        manifest=json.loads((SCOPE/'manifest.json').read_text())
        return (time.time()<manifest['grant']['expiresAt'] and manifest['grant']['groupName']==GROUP
                and request==manifest['request'] and request['groupName']==GROUP
                and request['context']['workflowId']==WORKFLOW)
    except (OSError,ValueError,KeyError):return False

def execute():
    sys.path.insert(0,str(ROOT/'skills/wechat-messaging/scripts'))
    from executor import deliver
    from wecom_adapter import WeComAdapter
    from ledger import atomic_json
    data=json.loads((SCOPE/'manifest.json').read_text())
    if not request_enabled(data['request']):raise ValueError('test-scope-invalid')
    os.environ['WECHAT_TEST_GROUPS']=GROUP
    result=deliver(data['request'],data['grant'],SCOPE/'delivery-ledger',WeComAdapter())
    atomic_json(SCOPE/'delivery-receipt.json',result)
    return result
if __name__=='__main__':print(json.dumps(execute(),ensure_ascii=False))

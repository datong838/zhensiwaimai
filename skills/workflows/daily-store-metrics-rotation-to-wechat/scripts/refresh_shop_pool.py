"""Refresh original brand roster under original post locks; no ledger rebuild/send."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def assert_no_live_owner(path):
    if not path.exists():
        return
    owner = json.loads(path.read_text())
    pid = owner.get('pid')
    if type(pid) is not int or pid <= 0:
        raise ValueError('post-owner-invalid')
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return
    raise ValueError('post-live-owner-busy')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--node', required=True)
    p.add_argument('--out', type=Path)
    p.add_argument('--timeout', type=int, default=480)
    a = p.parse_args()
    month = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m')
    out = (a.out or HERE.parent/'.runtime/monthly'/month/'brand-roster.json').resolve()
    if a.timeout < 1 or a.timeout > 600:
        raise ValueError('refresh-timeout-invalid')
    # A maintenance entry never steals a live lock even beyond its TTL.
    assert_no_live_owner(ROOT/'runtime/state/locks/taobao-brand-9230.lock')
    assert_no_live_owner(Path('/tmp/zhensi-post-9230.lock'))
    from metrics_rotation_daily import brand_lease
    with brand_lease() as check:
        result = subprocess.run([a.node, str(HERE/'collect_shop_pool_brand.mjs'), '--out', str(out)],
                                capture_output=True, text=True, timeout=a.timeout)
        check()
        if result.returncode:
            raise ValueError('original-roster-refresh-failed:' + result.stderr.strip()[-200:])
        snapshot = json.loads(out.read_text())
        sys.path.insert(0, str(ROOT/'runtime'))
        from monthly_work_registry import refresh, METRICS
        refresh(None, snapshot, flow=METRICS, month=month,
                today=datetime.now(ZoneInfo('Asia/Shanghai')).date())
        print(json.dumps({'ok': True, 'source': snapshot['source'], 'snapshot': str(out),
                          'total': snapshot['total'], 'openCount': snapshot['openCount'],
                          'orgsDone': snapshot['orgsDone'], 'sendAttempts': 0}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'ok': False, 'reason': str(exc), 'sendAttempts': 0}))
        sys.exit(1)

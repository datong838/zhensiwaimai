import contextlib
import json
import tempfile
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
import daily_ledger_delivery as daily
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/wechat-messaging/scripts"))


class Adapter:
    def __init__(self, outcome='verified'):
        self.calls = 0
        self.outcome = outcome
    def session(self, request):
        return contextlib.nullcontext()
    def preflight(self, request, output):
        return {'ok': True, 'resolvedGroup': daily.GROUP, 'inputEmpty': True}
    def send_one(self, request, item, work, grant, deadline):
        self.calls += 1
        return {'status': self.outcome, 'sendAttempts': 1}


class DailyLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.patch = patch.object(daily, 'ROOT', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.now = datetime(2026, 10, 25, 19, tzinfo=ZoneInfo('Asia/Shanghai'))
        self.skills = [{'name': n, 'enabled': True, 'dev_state': 'active'} for n in daily.FINAL]
        self.skills.append({'name':'meituan-intelligent-customer-service','enabled':True,'dev_state':'active'})
        self.runs = self.root / 'runtime/run_history/2026-10-25'
        self.runs.mkdir(parents=True)
        self.file = self.root / 'work/2026-10-25臻肆工作台账.xlsx'
        self.file.parent.mkdir()
        self.file.write_bytes(b'nonempty-frozen-xlsx-fixture')
        self.manifest()
        for name in daily.FINAL:
            self.write_run(name)
        self.write_run('meituan-intelligent-customer-service', stamp='2026-10-25T17:10:00')
    def manifest(self):
        (self.root/'runtime/skills_manifest.json').write_text(json.dumps({'skills':self.skills}))
    def write_run(self, name, stamp='2026-10-25T18:45:00', **extra):
        data={'skill':name,'status':'SUCCESS','finished_at':stamp, **extra}
        (self.runs/(name+'--record.json')).write_text(json.dumps(data))
    def test_before_final_slot_never_preflights(self):
        adapter=Adapter()
        result=daily.deliver_once(self.file,adapter=adapter,now=self.now.replace(hour=18,minute=29))
        self.assertEqual(result['status'],'blocked');self.assertEqual(adapter.calls,0)
    def test_old_slot_or_unknown_never_proves_final(self):
        name=next(iter(daily.FINAL))
        self.write_run(name,stamp='2026-10-25T17:50:00')
        self.assertIn(name,daily.readiness(self.now)[1])
        self.write_run(name,status='FAILED',category='UNKNOWN')
        self.assertIn(name,daily.readiness(self.now)[1])
    def test_cadence_pseudo_success_not_evidence(self):
        name=next(iter(daily.FINAL));self.write_run(name,detail='cadence 内跳过')
        self.assertFalse(daily.readiness(self.now)[0])
    def test_customer_requires_real_final_duty(self):
        self.write_run('meituan-intelligent-customer-service',stamp='2026-10-25T15:00:00')
        self.assertFalse(daily.readiness(self.now)[0])
        self.write_run('meituan-intelligent-customer-service',stamp='2026-10-25T17:10:00')
        self.assertTrue(daily.readiness(self.now)[0])
    def test_missing_final_schedule_cannot_pass(self):
        self.skills=[];self.manifest()
        self.assertFalse(daily.readiness(self.now)[0])
    def test_verified_one_send_then_idempotent(self):
        adapter=Adapter()
        self.assertEqual(daily.deliver_once(self.file,adapter=adapter,now=self.now)['status'],'verified')
        self.assertEqual(daily.deliver_once(self.file,adapter=adapter,now=self.now)['status'],'already_verified')
        self.assertEqual(adapter.calls,1)
    def test_unknown_never_retries(self):
        adapter=Adapter('unknown')
        self.assertEqual(daily.deliver_once(self.file,adapter=adapter,now=self.now)['status'],'unknown')
        daily.deliver_once(self.file,adapter=adapter,now=self.now)
        self.assertEqual(adapter.calls,1)
    def test_wrong_path_never_sends(self):
        adapter=Adapter();other=self.file.with_name('2026-10-24臻肆工作台账.xlsx');other.write_bytes(b'old')
        self.assertEqual(daily.deliver_once(other,adapter=adapter,now=self.now)['status'],'blocked')
        self.assertEqual(adapter.calls,0)
    def test_route_rejects_group_date_and_frozen_drift(self):
        daily.deliver_once(self.file,adapter=Adapter(),now=self.now)
        request=json.loads((daily.directory(self.now)/'request.json').read_text())
        self.assertTrue(daily.request_enabled(request,self.now))
        self.assertFalse(daily.request_enabled(request|{'groupName':'wrong'},self.now))
        self.assertFalse(daily.request_enabled(request,self.now.replace(day=26)))
        Path(request['items'][0]['path']).write_bytes(b'drift')
        self.assertFalse(daily.request_enabled(request,self.now))


if __name__ == '__main__':
    unittest.main()

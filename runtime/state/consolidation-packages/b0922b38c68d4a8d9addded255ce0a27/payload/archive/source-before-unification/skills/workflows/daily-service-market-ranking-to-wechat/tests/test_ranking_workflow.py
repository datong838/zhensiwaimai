import contextlib
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
BASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ranking_workflow', BASE / 'scripts/ranking_workflow.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
from registered_ui_routes import service_ranking_allowed


class Adapter:
    def __init__(self, verified=True, preflight=True):
        self.sends = 0
        self.verified = verified
        self.ready = preflight
    def session(self, request):
        return contextlib.nullcontext()
    def preflight(self, request, output):
        return {'ok': self.ready, 'resolvedGroup': w.GROUP, 'inputEmpty': True,
                'verificationLevel': 'wecom-ui-tree-target'}
    def send_one(self, request, item, *args):
        self.sends += 1
        return {'status': 'verified' if self.verified else 'unknown', 'sendAttempts': 1,
                'reason': None if self.verified else 'native-ui-inline-image-not-exposed'}


class RankingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state = self.root / 'state'
        self.patches = [patch.object(w, 'STATE', self.state), patch.object(w, 'integrity'),
                        patch.object(w, 'day_now', return_value='2026-10-26')]
        for p in self.patches: p.start()
        self.collect = Mock(side_effect=self.capture)
    def tearDown(self):
        for p in self.patches: p.stop()
        self.tmp.cleanup()
    def capture(self, folder):
        folder.mkdir(parents=True, exist_ok=True)
        file = folder / 'source.png'
        file.write_bytes(b'actual-test-fixture')
        return {'ok': True, 'file': str(file), 'sha256': hashlib.sha256(file.read_bytes()).hexdigest(),
                'browserPort': 9231, 'collectedAt': '2026-10-26T05:00:00Z'}
    def test_verified_never_recaptures_or_resends(self):
        a = Adapter()
        self.assertTrue(w.run(execute=True, collect=self.collect, adapter=a)['ok'])
        self.assertTrue(w.run(execute=True, collect=self.collect, adapter=a)['ok'])
        self.assertEqual((a.sends, self.collect.call_count), (1, 1))
    def test_existing_attempted_does_not_touch_browser_or_ui(self):
        folder=self.state/'days/2026-10-26';folder.mkdir(parents=True)
        (folder/'delivery.json').write_text(json.dumps({'state':'attempted','sendAttempts':None}))
        a=Adapter()
        self.assertEqual(w.run(execute=True,collect=self.collect,adapter=a)['status'],'unknown')
        self.assertEqual(a.sends,0);self.collect.assert_not_called()
    def test_unknown_never_recaptures_or_resends(self):
        a = Adapter(verified=False)
        self.assertFalse(w.run(execute=True, collect=self.collect, adapter=a)['ok'])
        prior = w.run(execute=True, collect=self.collect, adapter=a)
        self.assertEqual(prior['status'], 'unknown')
        self.assertEqual((a.sends, self.collect.call_count), (1, 1))
    def test_preflight_zero_send_reuses_frozen_item(self):
        a = Adapter(preflight=False)
        self.assertEqual(w.run(execute=True, collect=self.collect, adapter=a)['sendAttempts'], 0)
        a.ready = True
        self.assertTrue(w.run(execute=True, collect=self.collect, adapter=a)['ok'])
        self.assertEqual((a.sends, self.collect.call_count), (1, 1))
    def test_tampered_frozen_image_rejected_before_send(self):
        a = Adapter(preflight=False)
        w.run(execute=True, collect=self.collect, adapter=a)
        file = next((self.state / 'days/2026-10-26').glob('*.png'))
        file.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'frozen-binding'): w.run(execute=True, collect=self.collect, adapter=a)
        self.assertEqual(a.sends, 0)
    def test_old_source_date_rejected(self):
        def old(folder): return self.capture(folder) | {'collectedAt': '2026-10-25T05:00:00Z'}
        with self.assertRaisesRegex(ValueError, 'source-date'): w.run(execute=True, collect=old, adapter=Adapter())
    def test_route_only_exact_frozen_group_path_day_and_sha(self):
        day='2026-10-26'
        file=self.root/'skills/workflows/daily-service-market-ranking-to-wechat/.runtime/days'/day/(day+'-服务市场排名与考核指标.png')
        file.parent.mkdir(parents=True);file.write_bytes(b'fixture')
        item={'itemId':'service-ranking','type':'image','path':str(file),'name':file.name,'size':file.stat().st_size,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()}
        request={'groupName':w.GROUP,'context':{'workflowId':w.FLOW,'eventId':day+'-service-market-ranking','accountAlias':'main-wechat','channel':'desktop'},'items':[item]}
        self.assertTrue(service_ranking_allowed(request,root=self.root,day=day))
        for bad in [request|{'groupName':'电销+直播攻坚组'},request|{'items':[item|{'type':'file'}]},request|{'items':[item|{'sha256':'wrong'}]},request|{'items':[item|{'path':str(self.root/'other.png')}]},request|{'items':[item,item]},request|{'context':request['context']|{'eventId':'2026-10-25-service-market-ranking'}}]:
            self.assertFalse(service_ranking_allowed(bad,root=self.root,day=day))


if __name__ == '__main__': unittest.main()

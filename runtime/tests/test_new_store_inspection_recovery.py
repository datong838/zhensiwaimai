"""Exercise original daily orchestration with isolated collectors/adapters only."""
import importlib.util
import json
from datetime import datetime
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(kind):
    scripts = ROOT/f'skills/workflows/daily-new-stores-{kind}-audit-to-wechat/scripts'
    sys.path.insert(0, str(scripts))
    name = 'inspection_recovery_' + kind
    spec = importlib.util.spec_from_file_location(name, scripts/f'{kind}_daily.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, getattr(module, kind)


FLOWS = [(kind, *load(kind)) for kind in ('activity', 'decoration')]


class InspectionRecoveryTests(unittest.TestCase):
    def simulate(self, kind, daily, flow, outcomes, targets=1, delivery='verified'):
        with tempfile.TemporaryDirectory(prefix='inspection-recovery-') as folder, ExitStack() as stack:
            root = Path(folder)
            hits = [{'channel':'淘宝', 'name':f'测试店{i}', 'days':'1天'} for i in range(targets)]
            stack.enter_context(patch.object(flow, 'RUNTIME', root))
            stack.enter_context(patch.object(daily, 'todays_source', return_value=(root/'source.json',hits)))
            collect = stack.enter_context(patch.object(flow, 'collect', side_effect=outcomes))
            stack.enter_context(patch.object(flow, 'message', return_value='fixture-message'))
            send = stack.enter_context(patch.object(flow, 'deliver', return_value={'status':delivery,'sendAttempts':1}))
            reset = stack.enter_context(patch.object(daily, 'reset_chain_seed', return_value={'status':'fixture-reset'}))
            if kind == 'decoration':
                stack.enter_context(patch.object(daily, 'update_watchlist', return_value={}))
            result = daily.run(True)
            recovery = list(root.rglob('search-recovery.json'))
            return result, collect.call_count, send.call_count, reset.call_count, len(recovery)

    def good(self):
        return {'shopId':'1','targetStatus':{}}

    def test_search_timeout_recovers_once_before_one_delivery(self):
        for kind,daily,flow in FLOWS:
            with self.subTest(kind=kind):
                timeout=RuntimeError(kind+'-collection-skipped:shop-search-timeout')
                result,calls,sends,resets,proofs=self.simulate(kind,daily,flow,[timeout,self.good()])
                self.assertEqual((result['status'],calls,sends,resets,proofs),('complete',2,1,1,1))

    def test_persistent_timeout_keeps_pending_but_continues_independent_store(self):
        for kind,daily,flow in FLOWS:
            with self.subTest(kind=kind):
                timeout=RuntimeError(kind+'-collection-skipped:shop-search-timeout')
                result,calls,sends,resets,proofs=self.simulate(kind,daily,flow,[timeout,timeout,self.good()],2)
                self.assertEqual((result['status'],calls,sends,proofs),('unknown',3,1,1))
                self.assertEqual([s['status'] for s in result['shops']],['retry-required','verified'])
                self.assertEqual(result['recoveryRequired'],['测试店0'])
                self.assertIn('shop-search-timeout',result['reason'])

    def test_busy_never_retries_resets_sends_or_finishes(self):
        for kind,daily,flow in FLOWS:
            with self.subTest(kind=kind):
                busy=RuntimeError(kind+'-collection-skipped:post-lease-busy')
                result,calls,sends,resets,proofs=self.simulate(kind,daily,flow,[busy],2)
                self.assertEqual((result['status'],calls,sends,resets,proofs),('unknown',1,0,0,0))
                self.assertEqual(result['shops'][0]['status'],'skipped-busy')
                self.assertEqual(result['recoveryRequired'],['测试店0','测试店1'])

    def test_busy_single_target_is_never_completed(self):
        for kind,daily,flow in FLOWS:
            with self.subTest(kind=kind):
                busy=RuntimeError(kind+'-collection-skipped:post-lease-busy')
                result,calls,sends,resets,proofs=self.simulate(kind,daily,flow,[busy])
                self.assertEqual((result['status'],calls,sends,resets),('unknown',1,0,0))

    def test_busy_after_prior_success_still_does_not_reset_foreign_post(self):
        for kind,daily,flow in FLOWS:
            with self.subTest(kind=kind):
                busy=RuntimeError(kind+'-collection-skipped:post-lease-busy')
                result,calls,sends,resets,proofs=self.simulate(kind,daily,flow,[self.good(),busy],2)
                self.assertEqual((result['status'],calls,sends,resets),('unknown',2,1,0))

    def test_login_and_captcha_do_not_retry_or_reset(self):
        for kind,daily,flow in FLOWS:
            for error in ['login-required','验证码','account-risk']:
                with self.subTest(kind=kind,error=error):
                    result,calls,sends,resets,proofs=self.simulate(kind,daily,flow,[RuntimeError(error)])
                    self.assertEqual((result['status'],calls,sends,resets,proofs),('unknown',1,0,0,0))

    def test_only_explicit_nonoperating_is_completed_skip(self):
        for kind,daily,flow in FLOWS:
            for reason,expected in [('shop-not-operating:暂停营业','complete'),('shop-not-operating:已下线','complete'),('shop-not-operating','unknown'),('future-unknown-reason','unknown')]:
                with self.subTest(kind=kind,reason=reason):
                    result,calls,sends,resets,proofs=self.simulate(kind,daily,flow,[RuntimeError(kind+'-collection-skipped:'+reason)])
                    self.assertEqual(result['status'],expected);self.assertEqual((calls,sends,proofs),(1,0,0))

    def test_explicit_store_not_found_keeps_original_notice_delivery(self):
        for kind,daily,flow in FLOWS:
            with self.subTest(kind=kind):
                error=RuntimeError(kind+'-collection-skipped:shop-not-found:未搜索到店铺')
                result,calls,sends,resets,proofs=self.simulate(kind,daily,flow,[error])
                self.assertEqual((result['status'],calls,sends,proofs),('complete',1,1,0))
                self.assertEqual(result['shops'][0]['recordNote'],'店铺在主账号查不到未能检查')

    def test_sent_unknown_never_reenters_collection_retry(self):
        for kind,daily,flow in FLOWS:
            with self.subTest(kind=kind):
                result,calls,sends,resets,proofs=self.simulate(kind,daily,flow,[self.good()],2,'unknown')
                self.assertEqual((result['status'],calls,sends,proofs),('unknown',1,1,0))
                self.assertEqual(len(result['shops']),1)
                self.assertEqual(result['recoveryRequired'],['测试店0','测试店1'])

    def test_pending_store_without_inspection_cannot_heal_watchlist(self):
        _, daily, flow = FLOWS[1]
        with tempfile.TemporaryDirectory() as folder:
            watch = Path(folder)/'watchlist.json'
            entry = {'shopId':'1','shopName':'测试店0','state':'alerted','firstAlertDay':'2026-10-27'}
            watch.write_text(json.dumps({'schemaVersion':1,'entries':[entry]}))
            with patch.object(daily,'WATCHLIST',watch):
                result=daily.update_watchlist([{'sourceName':'测试店0','status':'retry-required','sendAttempts':0}],
                    datetime.now(flow.LOCAL_TZ).date().isoformat())
            self.assertEqual(result['healed'],[])
            self.assertEqual(json.loads(watch.read_text())['entries'],[entry])

    def test_persistent_timeout_reaches_original_recoverable_classification(self):
        sys.path.insert(0,str(ROOT/'runtime'))
        import skill_runner
        for kind,daily,flow in FLOWS:
            with self.subTest(kind=kind):
                error=RuntimeError(kind+'-collection-skipped:shop-search-timeout')
                result,*_=self.simulate(kind,daily,flow,[error,error])
                category,_,_=skill_runner.classify_with_receipt(json.dumps(result),1,False)
                self.assertEqual(category,skill_runner.CAT_RECOVERABLE)


if __name__=='__main__':
    unittest.main()

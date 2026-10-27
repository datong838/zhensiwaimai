"""Isolated monthly roster and planning contracts; no production IO."""
import copy
import importlib.util
from datetime import date
from pathlib import Path
import unittest
import sys
import tempfile
import json
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('monthly_registry', Path(__file__).parents[1]/'monthly_work_registry.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
sys.path.insert(0, str(Path(__file__).parents[1]))
import monthly_registry_cli as cli
TODAY = date(2026, 10, 27)


def snapshot():
    return {'complete': True, 'source': m.SOURCES[m.METRICS], 'account': 'gmfmmZH',
            'collectedAt': '2026-10-27T08:00:00Z', 'expectedOrgs': 2, 'orgsDone': 2,
            'failures': [], 'total': 2, 'openCount': 2,
            'shops': [{'shopId': '1001', 'shopName': '甲店', 'status': '营业中'},
                      {'shopId': '1002', 'shopName': '乙店', 'status': '营业中'}]}


def registry(s=None, old=None, flow=m.METRICS):
    return m.refresh(old, s or snapshot(), flow=flow, month='2026-10', today=TODAY)


class MonthlyRegistryTests(unittest.TestCase):
    def test_brand_workflows_share_open_only_roster_but_separate_calendars(self):
        s = snapshot()
        s['shops'].extend([{'shopId': '1003', 'shopName': '停业店', 'status': '暂停营业'},
                           {'shopId': '1004', 'shopName': '非营业店', 'status': '非营业中'}])
        s['total'] = 4
        a = registry(s)
        b = registry(s, flow=m.COUPON)
        self.assertEqual(set(a['merchants']), set(b['merchants']))
        self.assertEqual(len(a['merchants']), 2)
        a = m.plan_sa(a, [{'shopId': '1001'}], ['M01'])
        b = m.plan_sa(b, [{'shopId': '1002'}], ['coupon'])
        self.assertNotEqual(a['plan']['merchantKeys'], b['plan']['merchantKeys'])
        self.assertEqual(len(a['tasks']), 1)
        self.assertEqual(len(b['tasks']), 1)
        self.assertTrue(all(t['workItem'] == 'M01' for t in a['tasks'].values()))
        self.assertTrue(all(t['workItem'] == 'coupon' for t in b['tasks'].values()))

    def test_no_sa_is_not_an_empty_approved_plan(self):
        r = registry()
        self.assertIsNone(r['plan'])
        self.assertEqual(m.daily_plan(r, today=TODAY)['status'], 'waiting-sa')
        p = m.plan_sa(r, [], ['M01'])
        self.assertEqual(p['plan']['merchantKeys'], [])
        self.assertFalse(p['executionEnabled'])

    def test_source_failure_cannot_mutate_existing_registry(self):
        r = registry()
        before = copy.deepcopy(r)
        for key, value in [('complete', False), ('orgsDone', 1), ('total', 3),
                           ('openCount', 1), ('account', 'other'), ('failures', ['read-failed']),
                           ('collectedAt', '2026-09-30T12:00:00Z'),
                           ('collectedAt', '2026-10-28T12:00:00Z')]:
            s = snapshot(); s[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                registry(s, r)
        self.assertEqual(r, before)

    def test_duplicate_identity_rejected(self):
        s = snapshot(); s['shops'][1]['shopId'] = '1001'
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            registry(s)

    def test_sa_ambiguity_missing_duplicate_and_weak_selector_are_atomic(self):
        r = registry(); before = copy.deepcopy(r)
        for selected in [[{'name': '不存在'}], [{'shopId': '1001'}, {'shopId': '1001'}],
                         [{'platform': '淘宝闪购'}], [{'name': ''}]]:
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                m.plan_sa(r, selected, ['M01'])
        s = snapshot(); s['shops'][1]['shopName'] = '甲店'
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            m.plan_sa(registry(s), [{'name': '甲店'}], ['M01'])
        self.assertEqual(r, before)

    def test_refresh_preserves_unknown_and_disappeared_merchants(self):
        r = m.plan_sa(registry(), [{'shopId': '1001'}, {'shopId': '1002'}], ['M01'])
        key = next(k for k, t in r['tasks'].items() if t['merchantKey'].endswith('1001'))
        r['tasks'][key].update(status='unknown', evidence='original-receipt')
        s = snapshot(); s['shops'] = s['shops'][:1]; s['total'] = s['openCount'] = 1
        refreshed = registry(s, r)
        self.assertEqual(refreshed['tasks'][key], r['tasks'][key])
        self.assertEqual(len(refreshed['merchants']), 2)
        plan = m.daily_plan(refreshed, today=TODAY)
        self.assertEqual(sum(len(d['taskKeys']) for d in plan['days']), 0)
        self.assertEqual(len(plan['blocked']), 1)

    def test_distribution_total_and_capacity_overflow(self):
        r = m.plan_sa(registry(), [{'shopId': '1001'}, {'shopId': '1002'}], ['M01', 'M02', 'M03'])
        plan = m.daily_plan(r, today=TODAY)
        keys = [k for day in plan['days'] for k in day['taskKeys']]
        self.assertEqual(len(keys), 6)
        self.assertEqual(len(set(keys)), 6)
        self.assertEqual(plan['days'][-1]['date'], '2026-10-31')
        limited = m.daily_plan(r, today=TODAY, capacity=1)
        self.assertEqual(len(limited['overflow']), 1)
        for capacity in [True, 0, -1]:
            with self.assertRaises(ValueError):
                m.daily_plan(r, today=TODAY, capacity=capacity)

    def test_completed_and_attempted_are_never_scheduled_again(self):
        r = m.plan_sa(registry(), [{'shopId': '1001'}], ['M01', 'M02', 'M03'])
        for task, state in zip(r['tasks'].values(), ['verified', 'unknown', 'attempted']):
            task['status'] = state
        replanned = m.plan_sa(registry(old=r), [{'shopId': '1001'}], ['M01', 'M02', 'M03'])
        self.assertEqual(sum(len(d['taskKeys']) for d in m.daily_plan(replanned, today=TODAY)['days']), 0)

    def test_inspection_platforms_and_all_filters_required(self):
        s = {'complete': True, 'source': m.SOURCES[m.INSPECTION],
             'collectedAt': '2026-10-27T08:00:00Z', 'total': 2,
             'records': [{'platform': p, 'name': '同名店', 'city': '上海市'} for p in ['美团外卖', '淘宝闪购']],
             'platformProof': {p: {'filters': ['是会员', '营业中', '授权中'], 'paginationComplete': True,
                                   'total': 1} for p in ['美团外卖', '淘宝闪购']}}
        r = registry(s, flow=m.INSPECTION)
        self.assertEqual(len(r['merchants']), 2)
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            m.plan_sa(r, [{'name': '同名店', 'city': '上海市'}], ['inspection'])
        s['platformProof']['淘宝闪购']['filters'] = ['营业中']
        with self.assertRaisesRegex(ValueError, 'filters'):
            registry(s, flow=m.INSPECTION)

    def test_scope_cannot_cross_flow_or_month(self):
        r = registry()
        with self.assertRaisesRegex(ValueError, 'scope'):
            registry(old=r, flow=m.COUPON)
        with self.assertRaisesRegex(ValueError, 'month'):
            m.daily_plan(r, today=date(2026, 11, 1))

    def test_publish_rejects_bad_refresh_without_touching_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            cli.publish(p, snapshot(), flow=m.METRICS, month='2026-10', today=TODAY)
            old = (p/'latest.json').read_bytes()
            s = snapshot(); s['complete'] = False
            with self.assertRaises(ValueError):
                cli.publish(p, s, flow=m.METRICS, month='2026-10', today=TODAY)
            self.assertEqual((p/'latest.json').read_bytes(), old)

    def test_interrupted_publish_preserves_previous_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            cli.publish(p, snapshot(), flow=m.METRICS, month='2026-10', today=TODAY)
            old = (p/'latest.json').read_bytes(); entries = set(p.iterdir())
            real = cli.write_json
            def fail_manifest(path, data):
                if path.name == 'manifest.json':
                    raise OSError('injected-write-error')
                real(path, data)
            with patch.object(cli, 'write_json', side_effect=fail_manifest), self.assertRaises(OSError):
                cli.publish(p, snapshot(), flow=m.METRICS, month='2026-10', today=TODAY)
            self.assertEqual((p/'latest.json').read_bytes(), old)
            self.assertEqual(set(p.iterdir()), entries)

    def test_publish_integrity_and_independent_coupon_register(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            result = cli.publish(p, snapshot(), flow=m.COUPON, month='2026-10', today=TODAY)
            self.assertEqual(result['eligible'], 2)
            self.assertEqual(result['planState'], '待导入SA名单')
            pointer = json.loads((p/'latest.json').read_text())
            raw = p/pointer['generation']/'registry.json'
            raw.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'integrity'):
                cli.publish(p, snapshot(), flow=m.COUPON, month='2026-10', today=TODAY)


if __name__ == '__main__':
    unittest.main()

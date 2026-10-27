import sys
import json
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import supervisor_patrol as patrol


def page(url):
    return {'type': 'page', 'url': url}


class SupervisorPatrolChromeTests(unittest.TestCase):
    def progress(self, data):
        with patch.object(patrol.subprocess, 'run', return_value=SimpleNamespace(stdout=json.dumps(data))):
            return patrol.check_flows()

    def test_current_progress_rows_keep_unfinished_exclude_done_and_superseded(self):
        snap, findings = self.progress({'all_green': False, 'rows': [
            {'name': 'pending', 'done': False, 'reason': 'image unknown'},
            {'name': 'future', 'done': False, 'due': False},
            {'name': 'complete', 'done': True},
            {'name': 'old-slot', 'done': False, 'superseded': True},
        ]})
        self.assertEqual(snap['pending_count'], 2)
        self.assertEqual([r['name'] for r in snap['pending']], ['pending', 'future'])
        self.assertIn('2 条', findings[0]['detail'])

    def test_legacy_progress_list_remains_supported(self):
        snap, _ = self.progress({'all_green': False, 'pending': [{'skill': 'legacy'}]})
        self.assertEqual(snap['pending'], [{'name': 'legacy', 'reason': ''}])

    def test_missing_progress_list_is_unknown_not_zero(self):
        snap, findings = self.progress({'all_green': False})
        self.assertIsNone(snap['pending_count'])
        self.assertEqual(findings[0]['code'], 'progress-schema-unrecognized')

    def test_workbuddy_login_is_ignored_for_meituan_post(self):
        pages = [
            page('https://waimaie.meituan.com/imworkbench/home#/im/page/workbench/reception'),
            page('https://www.workbuddy.cn/login/?platform=workbuddy'),
        ]
        with patch.object(patrol, 'CHROME_PORTS', {9233: 'meituan-im'}), \
             patch.object(patrol, 'cdp_pages', return_value=(pages, None)):
            snap, findings = patrol.check_chrome('night')
        self.assertEqual(snap['ports']['9233']['login_pages'], 0)
        self.assertEqual(snap['ports']['9233']['ignored_non_business_login_pages'], 1)
        self.assertFalse(any(row['code'] == 'login-page-present:9233' for row in findings))

    def test_meituan_login_and_no_permission_still_fail_closed(self):
        for url in (
            'https://waimaie.meituan.com/login/',
            'https://waimaie.meituan.com/imworkbench/home#/noPermission',
        ):
            with self.subTest(url=url), \
                 patch.object(patrol, 'CHROME_PORTS', {9233: 'meituan-im'}), \
                 patch.object(patrol, 'cdp_pages', return_value=([page(url)], None)):
                snap, findings = patrol.check_chrome('night')
            self.assertEqual(snap['ports']['9233']['login_pages'], 1)
            self.assertTrue(any(row['code'] == 'login-page-present:9233' for row in findings))

    def test_other_posts_keep_existing_any_login_rule(self):
        with patch.object(patrol, 'CHROME_PORTS', {9231: 'taobao-agent-service'}), \
             patch.object(patrol, 'cdp_pages', return_value=([page('https://example.test/login')], None)):
            snap, findings = patrol.check_chrome('night')
        self.assertEqual(snap['ports']['9231']['login_pages'], 1)
        self.assertTrue(any(row['code'] == 'login-page-present:9231' for row in findings))


if __name__ == '__main__':
    unittest.main()

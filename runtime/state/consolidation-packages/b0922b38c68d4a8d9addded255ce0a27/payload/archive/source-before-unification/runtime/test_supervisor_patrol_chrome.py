import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import supervisor_patrol as patrol


def page(url):
    return {'type': 'page', 'url': url}


class SupervisorPatrolChromeTests(unittest.TestCase):
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

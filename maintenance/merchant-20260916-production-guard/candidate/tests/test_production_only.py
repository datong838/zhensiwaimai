import sys, unittest, tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import workflow_executor as w
import runtime_contract as c
import wechat_sender_executor as s
class ProductionOnly(unittest.TestCase):
    def args(self, path, group=None, auth=None):
        argv=['--output-dir',str(path),'--standing-authorization',auth or c.PRODUCTION_AUTHORIZATION]
        if group:argv+=['--group',group]
        return w.build_parser().parse_args(argv)
    def test_default_is_production(self):
        a=self.args('unused');self.assertEqual(a.group,s.PRODUCTION_GROUP)
        self.assertEqual(c.validate_policy(a,s)['cursorFile'],str(s.cursor_file(s.PRODUCTION_GROUP)))
    def test_old_test_authority_rejected_before_any_ui(self):
        for group in [s.TEST_GROUP,'other']:
            with self.subTest(group=group),tempfile.TemporaryDirectory() as d,patch.object(s,'STATE_DIR',Path(d)),patch.object(w.executor_integrity,'verify',return_value={'ok':True}),patch.object(w.desktop_wechat_sender,'preflight') as pre,patch.object(w.collector,'collect') as collect,patch.object(w.desktop_wechat_sender,'run') as send:
                result=w.execute(self.args(Path(d)/'run',group,s.TEST_AUTHORIZATION))
                self.assertFalse(result['ok']);self.assertEqual(result['error'],'production-only-target-required')
                pre.assert_not_called();collect.assert_not_called();send.assert_not_called()
    def test_wrong_auth_and_mobile_rejected(self):
        a=self.args('unused',auth=s.TEST_AUTHORIZATION)
        with self.assertRaisesRegex(RuntimeError,'authorization'):c.validate_policy(a,s)
        a=self.args('unused');a.wechat_channel='mobile'
        with self.assertRaisesRegex(RuntimeError,'channel'):c.validate_policy(a,s)
if __name__=='__main__':unittest.main()

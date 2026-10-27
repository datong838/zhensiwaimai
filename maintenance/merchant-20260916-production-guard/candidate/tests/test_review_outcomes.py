import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import runtime_contract as c

def item(send=False,commit=True,recover=False):
    rows=[{'stage':'定位、输入与单次发送' if send else '已有attempt只读复核','status':'PASS'}]
    if recover:rows.append({'stage':'发送后只读恢复','status':'PASS'})
    rows.append({'stage':'成功历史与原子游标提交','status':'PASS' if commit else 'FAIL'})
    return {'review':rows}

class ReviewOutcomes(unittest.TestCase):
    def test_old_reconcile_is_not_new_send(self):
        self.assertEqual(c.delivery_counts({'sent':1,'items':[item()]}),{'verifiedNewSends':0,'verifiedExisting':1,'unresolvedItems':0})
    def test_current_send_recovered_remains_new(self):
        self.assertEqual(c.delivery_counts({'items':[item(send=True,recover=True)]})['verifiedNewSends'],1)
    def test_mixed_and_commit_failure(self):
        self.assertEqual(c.delivery_counts({'items':[item(),item(True),item(True,False)]}),{'verifiedNewSends':1,'verifiedExisting':1,'unresolvedItems':1})
    def test_noop_is_not_send_pass(self):
        r=c.build_review({'runId':'test','ok':True,'elapsedMs':5,'stageMs':{'desktop_wechat':0},'stageResults':{'desktop_wechat':'PASS'},'wechat':{'mode':'execute-noop','sent':0}})
        row=next(x for x in r['rows'] if x['stage']=='desktop_wechat')
        self.assertEqual(row['status'],'NOOP');self.assertIn('未触发发送',c.render_review(r))
        self.assertEqual(r['verifiedNewSends'],0)
    def test_early_failure_is_skipped_not_noop(self):
        r=c.build_review({'runId':'test','ok':False,'elapsedMs':5,'stage':'executor_integrity','error':'hash-mismatch','stageMs':{'executor_integrity':5},'stageResults':{'executor_integrity':'FAIL'}})
        row=next(x for x in r['rows'] if x['stage']=='desktop_wechat')
        self.assertEqual(row['status'],'SKIPPED');self.assertIsNone(row['elapsedMs'])

if __name__=='__main__':unittest.main()

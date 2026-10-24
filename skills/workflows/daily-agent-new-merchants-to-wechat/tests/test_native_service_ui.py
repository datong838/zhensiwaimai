import sys, unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import native_service_ui as n

class UITests(unittest.TestCase):
    def test_unique_existing_tab(self):
        t=n.Tab(1,2,3,n.PREFIX+'home',2)
        self.assertEqual(n.unique_service_tab([t]),t)
        for rows in [[],[t,t]]:
            with self.assertRaises(n.UIError):n.unique_service_tab(rows)
    def test_foreground_tab_change_rejected(self):
        t=n.Tab(1,2,3,n.PREFIX+'home',2)
        n.verify_identity(t,t)
        for other in [n.Tab(1,2,3,n.PREFIX+'home',9),n.Tab(2,2,3,n.PREFIX+'home',2),n.Tab(1,2,3,'https://example.org/',2)]:
            with self.assertRaises(n.UIError):n.verify_identity(t,other)
    def test_sidebar_alone_is_not_completion(self):
        state={'url':n.PREFIX+'manager/agent/home','labels':['意向商户管理','商家意向列表'],'tableCount':1}
        self.assertTrue(n.intention_page(state))
        self.assertFalse(n.intention_page(state|{'tableCount':0}))
        self.assertFalse(n.intention_page(state|{'labels':['意向商户管理']}))
        self.assertFalse(n.intention_page(state|{'url':n.PREFIX+'home'}))
    def test_ambiguous_element_not_clicked(self):
        u=n.ServiceUI.__new__(n.ServiceUI);u.snapshot=Mock();u.guard=Mock();u.events=[]
        u.nodes=[{'element':object(),'label':'客户管理','actions':['AXPress'],'parent':None} for _ in range(2)]
        with patch.object(n.AX,'AXUIElementPerformAction') as click:
            with self.assertRaises(n.UIError):u.press('客户管理')
            click.assert_not_called()
    def test_text_child_uses_unique_parent(self):
        u=n.ServiceUI.__new__(n.ServiceUI);u.snapshot=Mock();u.guard=Mock();u.events=[]
        parent=object();u.nodes=[{'element':parent,'role':'AXMenuItem','label':'客户管理 99+','actions':['AXPress'],'parent':None},{'element':object(),'role':'AXStaticText','label':'客户管理','actions':[],'parent':0}]
        with patch.object(n.AX,'AXUIElementPerformAction',return_value=0) as click:
            u.press('客户管理');click.assert_called_once_with(parent,'AXPress')
    def test_full_observed_route(self):
        u=Mock();state={'url':n.PREFIX+'home','labels':[],'tableCount':0}
        u.stage.side_effect=lambda _,fn:fn();u.snapshot.side_effect=lambda:dict(state)
        def press(label):
            if label=='appstore 控制台':state.update(url=n.PREFIX+'manager/base/home',labels=['客户管理'])
            elif label=='客户管理':state['labels']+=['意向商户管理']
            elif label=='意向商户管理':state.update(url=n.PREFIX+'manager/agent/home',labels=['意向商户管理','商家意向列表'],tableCount=1)
            else:self.fail(label)
        u.press.side_effect=press
        def wait(predicate):
            self.assertTrue(predicate(state));return dict(state)
        u.wait.side_effect=wait
        result,already=n.run_route(u)
        self.assertTrue(n.intention_page(result));self.assertFalse(already)
        self.assertEqual([c.args[0] for c in u.press.call_args_list],['appstore 控制台','客户管理','意向商户管理'])
    def test_already_open_does_not_click(self):
        u=Mock();u.stage.side_effect=lambda _,fn:fn();u.snapshot.return_value={'url':n.PREFIX+'manager/agent/home','labels':['意向商户管理','商家意向列表'],'tableCount':1}
        _,already=n.run_route(u);self.assertTrue(already);u.press.assert_not_called()

if __name__=='__main__':unittest.main()

import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[4]/'runtime'))
from metrics_rotation_registration import register,FLOW

def test_registration_is_pending_idempotent_and_preserves_existing_tasks():
 m={'skills':[{'name':'existing','enabled':True,'steps':[{'argv':['existing']}]}],'ledger_template':[{'row':27,'skill':'existing','dev_state':'active'}]}
 p={'posts':{'brand':{'port':9230,'usedBy':['existing']},'other':{'port':9232,'usedBy':['other']}}}
 a,b=register(m,p)
 assert a['skills'][0]==m['skills'][0];assert a['skills'][1]['enabled'] is False
 assert a['ledger_template'][1]['row']==28;assert a['ledger_template'][1]['dev_state']=='pending'
 assert b['posts']['other']==p['posts']['other'];assert FLOW in b['posts']['brand']['usedBy']
 assert register(a,b)==(a,b);assert len(m['skills'])==1

def test_lease_renewal_preserves_owner_and_never_overwrites_another_flow(tmp_path):
 import json
 from metrics_rotation_daily import renew_post_lease
 p=tmp_path/'lease.json';p.write_text(json.dumps({'runId':FLOW,'pid':123,'acquiredAt':'2000-01-01T00:00:00'}))
 assert renew_post_lease(p,123);assert json.loads(p.read_text())['pid']==123
 p.write_text(json.dumps({'runId':'other','pid':456,'acquiredAt':'old'}));before=p.read_bytes()
 assert not renew_post_lease(p,123);assert p.read_bytes()==before

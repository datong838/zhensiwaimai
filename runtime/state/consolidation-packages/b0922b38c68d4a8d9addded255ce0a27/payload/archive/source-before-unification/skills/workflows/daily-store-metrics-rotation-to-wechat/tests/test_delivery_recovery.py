import json,contextlib,io,hashlib
import deliver_metric as dm

def test_legacy_attempted_blocks_and_monthly_verified_blocks_next_day(tmp_path,monkeypatch):
 monkeypatch.setattr(dm,'EVENTS',tmp_path/'events');dm.EVENTS.mkdir()
 image=tmp_path/'image.png';image.write_bytes(b'x'*20000);sha=hashlib.sha256(image.read_bytes()).hexdigest()
 def call(day):
  b=io.StringIO()
  with contextlib.redirect_stdout(b):dm.main(['--shop-id','101','--metric','M01','--image',str(image),'--date',day,'--group','G'])
  return json.loads(b.getvalue())
 p=dm.EVENTS/'2026-10-01-metrics-101-M01.json';p.write_text(json.dumps({'state':'attempted','sha256':sha}))
 assert call('2026-10-21')['status']=='unknown'
 p.write_text(json.dumps({'state':'verified','sha256':sha}));assert call('2026-10-22')['status']=='already_verified'
 assert call('2026-11-01')['status']=='planned'

def test_definite_blocked_with_send_attempt_is_unknown(tmp_path,monkeypatch):
 import sys,types
 called=[]
 class Adapter:
  def send_one(self,*a):called.append(1);return {'status':'blocked','sendAttempts':1}
 monkeypatch.setitem(sys.modules,'windows_adapter',types.SimpleNamespace(WindowsAdapter=Adapter))
 monkeypatch.setattr(dm,'EVENTS',tmp_path/'events');monkeypatch.setattr(dm,'RUNS',tmp_path/'runs');monkeypatch.setattr(dm,'GATE',tmp_path/'gate.json')
 image=tmp_path/'image.png';image.write_bytes(b'x'*20000)
 args=['--shop-id','101','--metric','M01','--image',str(image),'--date','2026-10-21','--group','G','--commit','--authorization-ref','isolated-test']
 b=io.StringIO()
 with contextlib.redirect_stdout(b):dm.main(args)
 assert json.loads(b.getvalue())['status']=='unknown'
 with contextlib.redirect_stdout(io.StringIO()):dm.main(args)
 assert len(called)==1

def test_monthly_delivery_lock_prevents_concurrent_send(tmp_path,monkeypatch):
 import fcntl
 monkeypatch.setattr(dm,'EVENTS',tmp_path/'events');dm.EVENTS.mkdir()
 with (dm.EVENTS/'2026-10-101-M01.lock').open('a+') as h:
  fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
  b=io.StringIO()
  with contextlib.redirect_stdout(b):code=dm.main(['--commit','--shop-id','101','--metric','M01','--date','2026-10-21','--image','missing.png'])
  assert code==3;assert json.loads(b.getvalue())['reason']=='delivery-busy'

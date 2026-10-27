import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import post_lease_file as subject


class PhysicalLeaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name).resolve()/'lease.lock'
    def acquire(self,run='run-new',**kw):
        return subject.mutate({'operation':'acquire','path':str(self.path),'runId':run,
                               'pid':os.getpid(),'style':'post','reentrant':True,**kw})
    def release(self,lease):
        return subject.mutate({'operation':'release','path':str(self.path),'lease':lease})
    def test_complete_atomic_payload_and_release(self):
        result=self.acquire();self.assertEqual(result['status'],'acquired')
        self.assertEqual(json.loads(self.path.read_text()),result['lease'])
        self.assertEqual(self.release(result['lease'])['status'],'released')
        self.assertFalse(self.path.exists());self.assertTrue(Path(str(self.path)+'.guard').exists())
    def test_alive_owner_never_taken_even_after_extreme_ttl(self):
        owner={'runId':'other','pid':os.getpid(),'acquiredAt':1};self.path.write_text(json.dumps(owner));before=self.path.read_bytes()
        self.assertEqual(self.acquire()['status'],'busy');self.assertEqual(self.path.read_bytes(),before)
    def test_confirmed_dead_fresh_owner_recovers_without_ttl_wait(self):
        p=subprocess.Popen([sys.executable,'-c','pass']);p.wait()
        self.path.write_text(json.dumps({'runId':'dead','pid':p.pid,'acquiredAt':10**15}))
        self.assertEqual(self.acquire()['status'],'acquired')
    def test_invalid_or_unreadable_owner_is_not_removed(self):
        for data in ['{','null','{}','{"pid":true}','{"pid":0}','{"pid":-1}']:
            with self.subTest(data=data):
                self.path.write_text(data);self.assertEqual(self.acquire()['status'],'busy');self.assertEqual(self.path.read_text(),data)
    def test_permission_uncertainty_is_alive(self):
        with patch.object(subject.os,'kill',side_effect=PermissionError):self.assertTrue(subject.alive(123))
        self.assertIsNone(subject.alive(True));self.assertIsNone(subject.alive(None))
    def test_same_run_requires_same_pid_and_explicit_reentrance(self):
        first=self.acquire();self.assertEqual(self.acquire()['lease'],first['lease'])
        self.assertEqual(self.acquire(reentrant=False)['status'],'busy')
        self.path.write_text(json.dumps({'runId':'run-new','pid':os.getppid(),'acquiredAt':1}))
        self.assertEqual(self.acquire()['status'],'busy')
    def test_old_lease_cannot_release_reacquired_owner(self):
        first=self.acquire()['lease'];self.release(first);second=self.acquire()['lease']
        self.assertNotEqual(first['leaseId'],second['leaseId'])
        self.assertEqual(self.release(first)['status'],'mismatch');self.assertEqual(json.loads(self.path.read_text()),second)
    def test_modified_pid_run_or_time_never_releases(self):
        lease=self.acquire()['lease']
        for k,v in [('pid',os.getpid()+1),('runId','wrong'),('acquiredAt',0),('leaseId','wrong')]:
            with self.subTest(k=k):self.assertEqual(self.release(lease|{k:v})['status'],'mismatch')
        self.assertTrue(self.path.exists())
    def test_legacy_exact_owner_can_release_without_new_nonce(self):
        legacy={'runId':'old','pid':os.getpid(),'acquiredAt':1};self.path.write_text(json.dumps(legacy))
        self.assertEqual(self.release(legacy)['status'],'released')
    def test_kernel_guard_releases_after_holder_process_killed(self):
        guard=str(self.path)+'.guard'
        code="import fcntl,sys,time; f=open(sys.argv[1],'a+');fcntl.flock(f,fcntl.LOCK_EX);print('ready',flush=True);time.sleep(30)"
        p=subprocess.Popen([sys.executable,'-c',code,guard],stdout=subprocess.PIPE,text=True)
        try:
            self.assertEqual(p.stdout.readline().strip(),'ready');p.kill();p.wait()
            self.assertEqual(self.acquire()['status'],'acquired')
        finally:
            if p.poll() is None:p.kill();p.wait()
            p.stdout.close()
    def test_concurrent_brokers_have_only_one_winner(self):
        script=str(Path(subject.__file__))
        def contender(n):
            request={'operation':'acquire','path':str(self.path),'runId':f'run-{n}','pid':os.getpid(),'style':'post','reentrant':True}
            result=subprocess.run([sys.executable,script],input=json.dumps(request),text=True,capture_output=True,timeout=5,check=True)
            return json.loads(result.stdout)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(contender,range(16)))
        self.assertEqual(sum(r['status']=='acquired' for r in results),1)
        winner=next(r['lease'] for r in results if r['status']=='acquired');self.assertEqual(json.loads(self.path.read_text()),winner)
    def test_symlink_payload_or_guard_never_follows_foreign_file(self):
        target=self.path.parent/'foreign';target.write_text('{"not":"a lease"}')
        self.path.symlink_to(target);self.assertEqual(self.acquire()['status'],'busy');self.path.unlink()
        Path(str(self.path)+'.guard').unlink();Path(str(self.path)+'.guard').symlink_to(target)
        with self.assertRaises(OSError):self.acquire()
        self.assertEqual(target.read_text(),'{"not":"a lease"}')

    def fault_writer(self,after_link):
        code='''import sys,os,time
sys.path.insert(0,sys.argv[1]);import post_lease_file as s
real=s.os.link
def blocked(*a,**kw):
 if sys.argv[3]=='after':real(*a,**kw)
 print('ready',flush=True);time.sleep(30)
s.os.link=blocked
s.mutate({'operation':'acquire','path':sys.argv[2],'pid':os.getpid(),'runId':'fault-writer','style':'post'})
'''
        p=subprocess.Popen([sys.executable,'-c',code,str(Path(subject.__file__).parent),str(self.path),
                            'after' if after_link else 'before'],stdout=subprocess.PIPE,text=True)
        try:
            self.assertEqual(p.stdout.readline().strip(),'ready');p.kill();p.wait()
        finally:
            if p.poll() is None:p.kill();p.wait()
            p.stdout.close()
    def test_writer_death_before_publication_leaves_no_empty_lease(self):
        self.fault_writer(False);self.assertFalse(self.path.exists())
        self.assertEqual(self.acquire()['status'],'acquired')
    def test_writer_death_after_publication_leaves_complete_reclaimable_lease(self):
        self.fault_writer(True);self.assertEqual(json.loads(self.path.read_text())['runId'],'fault-writer')
        self.assertEqual(self.acquire()['status'],'acquired')


if __name__=='__main__':unittest.main()

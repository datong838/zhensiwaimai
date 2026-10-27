import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import business_storage as storage
import migrate_business_storage as migration


class BusinessStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        base=Path(self.temp.name).resolve();self.root=base/'repo';(self.root/'runtime').mkdir(parents=True)
        self.old=base/'external';self.old.mkdir();(self.old/'.hidden').mkdir()
        self.marker=self.old/'.hidden/attempt.json';self.original=b'{"state":"unknown","eventId":"/old/external/marker.json","sendAttempts":1}\n';self.marker.write_bytes(self.original)
        self.second=base/'other';self.second.mkdir();(self.second/'checkpoint.json').write_text('{"cursor":42}')
        self.objects={'appeals':{'legacy':str(self.old),'target':'state/shared/appeals'},'video':{'legacy':str(self.second),'target':'data/video'}}
        (self.root/'runtime/business_storage_catalog.json').write_text(json.dumps({'schemaVersion':1,'objects':self.objects}))
        self.plan=lambda keys=None:migration.make_plan(self.root,keys or ['appeals'])
        self.apply=lambda p:migration.apply_plan(p,root=self.root,idle_check=lambda _:None)
        self.path=lambda key='appeals':storage.business_path(key,root=self.root)
    def test_read_only_plan_and_no_automatic_existing_target_switch(self):
        before=sorted(str(p) for p in self.root.rglob('*'));p=self.plan();self.assertEqual(before,sorted(str(p) for p in self.root.rglob('*')))
        self.assertEqual(self.path(),self.old)
        (self.root/'state/shared/appeals').mkdir(parents=True)
        self.assertEqual(self.path(),self.old)
    def test_copy_activation_preserves_unknown_and_original_event_bytes(self):
        p=self.plan();self.apply(p)
        self.assertEqual(self.path(),self.root/'state/shared/appeals')
        self.assertEqual(self.marker.read_bytes(),self.original)
        self.assertEqual((self.path()/'.hidden/attempt.json').read_bytes(),self.original)
        self.assertEqual(migration.inventory(self.path()),p['objects']['appeals']['inventory'])
    def test_source_drift_prevents_activation(self):
        p=self.plan();self.marker.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'source-changed'):self.apply(p)
        self.assertFalse((self.root/storage.LAYOUT).exists())
    def test_target_collision_refused(self):
        p=self.plan();(self.root/'state/shared/appeals').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError,'collision'):self.apply(p)
        self.assertEqual(self.path(),self.old)
    def test_symbolic_link_is_not_followed(self):
        (self.old/'link').symlink_to(self.second)
        with self.assertRaisesRegex(ValueError,'symlink'):self.plan()
    def test_unknown_key_and_path_escape_refused(self):
        with self.assertRaisesRegex(ValueError,'unknown'):self.path('not-listed')
        for name in ['../outside','/outside']:
            with self.assertRaises(ValueError):storage.internal_path(self.root,name)
    def test_idle_gate_blocks_copy(self):
        with self.assertRaisesRegex(ValueError,'writer-active'):
            migration.apply_plan(self.plan(),root=self.root,idle_check=lambda _:(_ for _ in ()).throw(ValueError('writer-active')))
        self.assertFalse((self.root/'state/shared/appeals').exists())
    def test_existing_source_lock_blocks_migration_without_touching_state(self):
        import fcntl
        lock=self.old/'sender.lock';lock.write_bytes(b'')
        plan=self.plan()
        with lock.open('rb') as held:
            fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):self.apply(plan)
        self.assertEqual(self.marker.read_bytes(),self.original)
        self.assertFalse((self.root/storage.LAYOUT).exists())
    def test_second_copy_failure_does_not_publish_any_new_authority(self):
        plan=self.plan(['appeals','video']);real=shutil.copytree
        def copy(source,*args,**kwargs):
            if source==str(self.second):raise OSError('fixture-copy-failure')
            return real(source,*args,**kwargs)
        with patch.object(migration.shutil,'copytree',side_effect=copy):
            with self.assertRaisesRegex(OSError,'fixture-copy-failure'):self.apply(plan)
        self.assertFalse((self.root/storage.LAYOUT).exists());self.assertEqual(self.path(),self.old)
    def test_pristine_rollback_retains_both_trees(self):
        p=self.plan();self.apply(p);migration.rollback(p['id'],root=self.root,idle_check=lambda _:None)
        self.assertEqual(self.path(),self.old);self.assertTrue((self.root/'state/shared/appeals/.hidden/attempt.json').exists())
    def test_new_target_writes_block_rollback(self):
        p=self.plan();self.apply(p);(self.path()/'new.json').write_text('{"cursor":43}')
        with self.assertRaisesRegex(ValueError,'new-writes'):migration.rollback(p['id'],root=self.root,idle_check=lambda _:None)
        self.assertEqual(self.path(),self.root/'state/shared/appeals')
    def test_bad_activation_evidence_refused(self):
        p=self.plan();self.apply(p)
        proof=self.root/'runtime/state/storage-migrations'/p['id']/'activation.json';proof.write_text('{}')
        with self.assertRaisesRegex(ValueError,'proof-invalid'):self.path()
    def test_unmigrated_object_remains_at_existing_authority(self):
        self.apply(self.plan());self.assertEqual(self.path('video'),self.second)
    def test_forged_plan_target_refused(self):
        p=self.plan();p['objects']['appeals']['target']='work/overwrite'
        with self.assertRaisesRegex(ValueError,'scope-invalid'):self.apply(p)
    def test_python_node_resolvers_agree_after_activation_from_other_cwd(self):
        self.apply(self.plan())
        node='/Users/ddt/.codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
        module=Path(storage.__file__).with_suffix('.mjs').as_uri()
        code=f"import {{businessPath}} from {json.dumps(module)}; console.log(businessPath('appeals',{{root:{json.dumps(str(self.root))}}}));"
        result=subprocess.check_output([node,'--input-type=module','-e',code],cwd=self.old,text=True).strip()
        self.assertEqual(result,str(self.path()))
    def test_original_bridge_never_replays_moved_unknown_attempted_or_verified_marker(self):
        import sys
        from types import SimpleNamespace
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/wechat-messaging/scripts'))
        import workflow_bridge as bridge
        from unittest.mock import Mock
        folder=self.root/'state/shared/bridge-fixture';folder.mkdir(parents=True)
        item={'itemId':'0','type':'file','path':str(self.marker),'name':'report.xlsx','size':len(self.original),'sha256':'a'*64}
        request={'groupName':'fixture-group','items':[item],'context':{'eventId':str(folder/'marker.json')}}
        args=SimpleNamespace(ledger=str(folder),marker_name='marker.json',output_dir=str(self.root/'out'),payload_type='file',execute=True,reconcile=False)
        adapter=Mock(side_effect=AssertionError('adapter must not run'))
        for state in ['unknown','attempted','verified']:
            prior={'state':state,'verified':state=='verified','groupName':'fixture-group','payloadType':'file',
                   'payloads':[{'path':'/old/report.xlsx','name':'report.xlsx','size':len(self.original),'sha256':'a'*64}],
                   'sendAttempts':1,'commonReceipt':{'eventId':'/old/ledger/marker.json','items':[]}}
            marker=folder/'marker.json';marker.write_text(json.dumps(prior));before=marker.read_bytes()
            with patch.object(bridge,'prepare',return_value=(request,{})),patch.object(bridge,'assert_correction_origin'),patch.object(bridge,'verify_pre_dispatch_dependencies'):
                result=bridge.execute(args,adapter_factory=adapter)
            self.assertEqual(result['newSendAttempts'],0);self.assertEqual(before,marker.read_bytes())
        adapter.assert_not_called()
    def test_dangling_target_symlink_refused(self):
        (self.root/'state/shared').mkdir(parents=True)
        (self.root/'state/shared/appeals').symlink_to('/missing/outside')
        with self.assertRaisesRegex(ValueError,'symlink'):self.path()

if __name__=='__main__':unittest.main()

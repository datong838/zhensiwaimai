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

class SourceAliasMigrationTests(unittest.TestCase):
    def setUp(self):
        import os
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        base=Path(self.t.name).resolve();self.root=base/'repo';(self.root/'runtime').mkdir(parents=True)
        self.entry=base/'reports-entry';self.real=base/'nvme-reports';self.real.mkdir();self.entry.symlink_to(self.real,target_is_directory=True)
        self.original=b'{"state":"unknown","eventId":"old-event","sendAttempts":1}\n';(self.real/'marker.json').write_bytes(self.original)
        self.key='jinsha-reports';self.target='data/reports/jinsha'
        (self.root/'runtime/business_storage_catalog.json').write_text(json.dumps({'schemaVersion':1,'objects':{self.key:{'legacy':str(self.entry),'target':self.target}}}))
        allowed=patch.object(migration,'APPROVED_SOURCE_LINKS',{self.key:(str(self.entry),str(self.real))});allowed.start();self.addCleanup(allowed.stop)
    def plan(self):return migration.make_plan(self.root,[self.key])
    def apply(self,p,idle=lambda _:None):return migration.apply_plan(p,root=self.root,idle_check=idle)
    def test_only_approved_entry_and_target_are_bound_in_read_only_plan(self):
        import os
        before=self.entry.lstat();raw=os.readlink(self.entry);p=self.plan();binding=p['objects'][self.key]['sourceBinding']
        self.assertEqual(binding['entry'],str(self.entry));self.assertEqual(binding['resolvedSource'],str(self.real));self.assertEqual(binding['linkTarget'],raw)
        self.assertEqual(self.entry.lstat().st_ino,before.st_ino);self.assertEqual((self.real/'marker.json').read_bytes(),self.original)
        self.assertFalse((self.root/storage.LAYOUT).exists())
    def test_apply_copies_real_directory_preserving_original_link_and_bytes(self):
        import os
        p=self.plan();ino=self.entry.lstat().st_ino;raw=os.readlink(self.entry);copy=shutil.copytree
        with patch.object(migration.shutil,'copytree',wraps=copy) as called:self.apply(p)
        self.assertEqual(called.call_args.args[0],str(self.real));self.assertTrue(self.entry.is_symlink());self.assertEqual(self.entry.lstat().st_ino,ino);self.assertEqual(os.readlink(self.entry),raw)
        self.assertEqual((self.real/'marker.json').read_bytes(),self.original);self.assertEqual((self.root/self.target/'marker.json').read_bytes(),self.original)
        proof=json.loads((self.root/'runtime/state/storage-migrations'/p['id']/'activation.json').read_text())
        self.assertEqual(proof['objects'][self.key]['sourceBinding'],p['objects'][self.key]['sourceBinding'])
    def test_wrong_key_or_entry_remains_rejected(self):
        with patch.object(migration,'APPROVED_SOURCE_LINKS',{}):
            with self.assertRaisesRegex(ValueError,'not-approved'):self.plan()
        with patch.object(migration,'APPROVED_SOURCE_LINKS',{self.key:(str(self.entry)+'-other',str(self.real))}):
            with self.assertRaisesRegex(ValueError,'not-approved'):self.plan()
    def test_other_target_or_link_chain_is_not_approved(self):
        other=self.root.parent/'other';other.mkdir();self.entry.unlink();self.entry.symlink_to(other)
        with self.assertRaisesRegex(ValueError,'target-mismatch'):self.plan()
        self.entry.unlink();middle=self.root.parent/'middle';middle.symlink_to(self.real);self.entry.symlink_to(middle)
        with self.assertRaisesRegex(ValueError,'target-mismatch'):self.plan()
    def test_entry_recreated_or_retargeted_after_plan_is_rejected(self):
        p=self.plan();self.entry.rename(self.entry.with_name('old-entry'));self.entry.symlink_to(self.real)
        with self.assertRaisesRegex(ValueError,'binding-changed'):self.apply(p)
        self.assertFalse((self.root/storage.LAYOUT).exists())
    def test_real_directory_replacement_after_plan_is_rejected(self):
        p=self.plan();saved=self.real.with_name('original-real');self.real.rename(saved);shutil.copytree(saved,self.real)
        with self.assertRaisesRegex(ValueError,'binding-changed'):self.apply(p)
        self.assertFalse((self.root/storage.LAYOUT).exists())
    def test_missing_binding_cannot_follow_an_old_unbound_link_plan(self):
        p=self.plan();p['objects'][self.key].pop('sourceBinding')
        with self.assertRaisesRegex(ValueError,'binding-changed'):self.apply(p)
    def test_nested_links_and_linked_real_target_are_still_refused(self):
        (self.real/'nested').symlink_to('/nonexistent/outside')
        with self.assertRaisesRegex(ValueError,'symlink|nonregular'):self.plan()
        (self.real/'nested').unlink();saved=self.real.with_name('saved-real');self.real.rename(saved);self.real.symlink_to(saved)
        with self.assertRaisesRegex(ValueError,'not-canonical'):self.plan()
    def test_idle_check_is_not_bypassed_for_approved_link(self):
        from unittest.mock import Mock
        p=self.plan();idle=Mock(side_effect=ValueError('writer-still-active'))
        with self.assertRaisesRegex(ValueError,'writer-still-active'):self.apply(p,idle)
        idle.assert_called_once_with(self.root);self.assertFalse((self.root/self.target).exists())
    def test_real_source_file_lock_is_preserved_and_blocks_copy(self):
        import fcntl
        lock=self.real/'sender.lock';lock.write_bytes(b'');p=self.plan()
        with lock.open('rb') as held:
            fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):self.apply(p)
        self.assertFalse((self.root/storage.LAYOUT).exists());self.assertTrue(self.entry.is_symlink())
    def test_idle_writer_detection_includes_approved_real_source_arguments(self):
        from types import SimpleNamespace
        exists=Path.exists
        def check(path):return False if str(path).startswith('/tmp/zhensi-post-') else exists(path)
        with patch.object(migration.subprocess,'run',return_value=SimpleNamespace(returncode=1)),patch.object(migration.subprocess,'check_output',return_value='555 other-writer --output '+str(self.real)),patch.object(Path,'exists',check):
            with self.assertRaisesRegex(ValueError,'writer-process-present'):migration.assert_idle(self.root)
    def test_link_retarget_during_copy_never_activates(self):
        p=self.plan();other=self.real.with_name('wrong-target');other.mkdir();(other/'marker.json').write_bytes(b'wrong');real_copy=shutil.copytree
        def switch(source,*args,**kwargs):
            result=real_copy(source,*args,**kwargs);self.entry.rename(self.entry.with_name('saved-entry'));self.entry.symlink_to(other);return result
        with patch.object(migration.shutil,'copytree',side_effect=switch):
            with self.assertRaisesRegex(ValueError,'target-mismatch|binding-changed'):self.apply(p)
        self.assertFalse((self.root/storage.LAYOUT).exists());self.assertEqual((self.real/'marker.json').read_bytes(),self.original)
    def test_rollback_restores_authority_without_changing_source_link(self):
        import os
        p=self.plan();self.apply(p);raw=os.readlink(self.entry);ino=self.entry.lstat().st_ino
        migration.rollback(p['id'],root=self.root,idle_check=lambda _:None)
        self.assertEqual(storage.business_path(self.key,root=self.root),self.entry);self.assertEqual(os.readlink(self.entry),raw);self.assertEqual(self.entry.lstat().st_ino,ino)


if __name__=='__main__':unittest.main()

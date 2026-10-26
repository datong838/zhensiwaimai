import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import prepare_code_consolidation as tool

IGNORE='state/\nruntime/state/\n**/.runtime/\noutputs/\nrecords/\nwork/\ndata/\narchive/\n.env\n'


class CodeConsolidationTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        base=Path(self.t.name).resolve();self.source=base/'source';self.source.mkdir();self.root=base/'runtime';self.root.mkdir()
        self.git(self.source,'init','-q');(self.source/'tracked.py').write_text('source history');(self.source/'.gitignore').write_text(IGNORE)
        self.git(self.source,'add','.');self.git(self.source,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','original')
        self.git(self.source,'tag','original-tag');self.git(self.source,'update-ref','refs/custom/preserved',self.git(self.source,'rev-parse','HEAD').decode().strip())
        (self.root/'.gitignore').write_text(IGNORE);(self.root/'worker.py').write_text('live working tree must stay')
        (self.root/'state').mkdir();(self.root/'state/cursor.json').write_text('{"cursor":42,"state":"unknown"}')
        old=base/'external';old.mkdir()
        desktop=old/'desktop';desktop.mkdir();(desktop/'wechat_interaction_lock.py').write_text('from pathlib import Path\nLOCK_PATH = Path(__file__).resolve().parents[1] / ".runtime" / "wechat-ui-interaction.lock"\n')
        chrome=old/'chrome';chrome.mkdir();(chrome/'background_chrome.mjs').write_text('export const version=1;\n')
        installed=old/'installed';(installed/'scripts').mkdir(parents=True)
        windows=old/'windows';windows.mkdir();(windows/'client.py').write_text('legacy_client=True\n')
        self.config={'schemaVersion':1,'assets':{
            'desktop-tools':{'source':str(desktop),'target':'vendor/legacy-app-controler/wechat-desktop-control/scripts','originalArchive':'archive/external-code-originals/desktop-tools'},
            'chrome-controller':{'source':str(chrome),'target':'vendor/dedicated-chrome-controller','originalArchive':'archive/external-code-originals/chrome-controller'},
            'installed-skill':{'source':str(installed),'target':'archive/installed-skill'},
            'windows-driver':{'source':str(windows),'target':'archive/compat/wechat-windows-driver'}},
            'bindings':{str(desktop):'vendor/legacy-app-controler/wechat-desktop-control/scripts',str(chrome):'vendor/dedicated-chrome-controller',str(installed):'vendor/installed-taobao-skill',str(windows):'archive/compat/wechat-windows-driver'}}
        self.guard='skills/workflows/daily-top10-to-wechat-group/scripts/runtime_guard.py'
        self.write(self.guard,"SHARED="+repr(str(desktop))+'\n')
        sha=tool.file_sha(self.root/self.guard)
        self.dep='skills/wechat-messaging/dependencies.json'
        self.history=[{'oldSha256':sha,'oldPath':str(desktop)}]
        self.write(self.dep,json.dumps({'schemaVersion':1,'files':{str(desktop/'wechat_interaction_lock.py'):tool.file_sha(desktop/'wechat_interaction_lock.py')},'rebindHistory':self.history}))
        self.policy='skills/workflows/daily-top10-to-wechat-group/runtime-policy.json'
        self.write(self.policy,json.dumps({'schemaVersion':1,'files':{'guard':{'path':str(self.root/self.guard),'sha256':sha},'dependencies':{'path':str(self.root/self.dep),'sha256':tool.file_sha(self.root/self.dep)}},'rebindHistory':self.history}))
        self.background='skills/workflows/daily-taobao-download-to-jinsha/scripts/background_browser_executor.mjs'
        self.entry='skills/workflows/daily-taobao-download-to-jinsha/scripts/entrypoint.mjs'
        self.write(self.background,"const CONTROLLER="+repr(str(chrome/'background_chrome.mjs'))+';\n')
        self.write(self.entry,"const INSTALLED_ENTRYPOINT="+repr(str(installed/'scripts/entrypoint.mjs'))+";\nconst EXECUTOR_SHA256='"+tool.file_sha(self.root/self.background)+"';\n")
        self.write('skills/workflows/daily-taobao-download-to-jinsha/SKILL.md','canonical skill fixture')
        shutil.copy2(self.root/self.entry,installed/'scripts/entrypoint.mjs');(installed/'SKILL.md').write_text('canonical skill fixture')
        cp=patch.object(tool,'load_catalog',return_value=self.config);cp.start();self.addCleanup(cp.stop)
        self.plan=lambda:tool.plan(self.root,self.source)
        self.prepare=lambda p=None:tool.prepare(p or self.plan(),idle_check=lambda _:None)
    def git(self,where,*args):return subprocess.check_output(['git','-C',str(where),*args],stderr=subprocess.DEVNULL)
    def write(self,name,text):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    def test_default_plan_is_read_only(self):
        before=tool.snapshot(self.root);p=self.plan();self.assertEqual(before,tool.snapshot(self.root));self.assertFalse((self.root/'.git').exists());self.assertEqual(p['mode'],'read-only')
    def test_prepared_patch_hash_chain_and_history_preservation(self):
        package=self.prepare();proof=json.loads((package/'prepared.json').read_text())
        self.assertFalse(proof['productionCodeModified']);self.assertTrue(proof['sharedSealRebindingRequired'])
        policy=json.loads((package/'patches'/self.policy).read_text());deps=json.loads((package/'patches'/self.dep).read_text())
        self.assertEqual(policy['files']['guard']['sha256'],tool.file_sha(package/'patches'/self.guard))
        self.assertEqual(policy['files']['dependencies']['sha256'],tool.file_sha(package/'patches'/self.dep))
        self.assertEqual(policy['rebindHistory'],self.history);self.assertEqual(deps['rebindHistory'],self.history)
        self.assertIn(tool.file_sha(package/'patches'/self.background),(package/'patches'/self.entry).read_text())
        self.assertEqual((package/'payload/vendor/installed-taobao-skill/scripts/entrypoint.mjs').read_bytes(),(package/'patches'/self.entry).read_bytes())
        original=Path(self.config['assets']['desktop-tools']['source'])/'wechat_interaction_lock.py'
        self.assertEqual((package/'payload/archive/external-code-originals/desktop-tools/wechat_interaction_lock.py').read_bytes(),original.read_bytes())
    def test_vendored_interaction_lock_keeps_original_global_lock_domain(self):
        import importlib.util
        package=self.prepare();old=Path(self.config['assets']['desktop-tools']['source'])/'wechat_interaction_lock.py'
        new=package/'payload/vendor/legacy-app-controler/wechat-desktop-control/scripts/wechat_interaction_lock.py'
        paths=[]
        for i,file in enumerate([old,new]):
            spec=importlib.util.spec_from_file_location('fixture_lock_'+str(i),file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);paths.append(m.LOCK_PATH)
        self.assertEqual(paths[0],paths[1])
        deps=json.loads((package/'patches'/self.dep).read_text())
        expected=str(self.root/'vendor/legacy-app-controler/wechat-desktop-control/scripts/wechat_interaction_lock.py')
        self.assertEqual(deps['files'][expected],tool.file_sha(new))
    def test_dynamic_extra_entrypoints_and_transitive_current_manifests(self):
        desktop=Path(self.config['assets']['desktop-tools']['source'])
        self.write('skills/wechat-messaging/scripts/dependency_maintenance.py','SHARED_ROOT='+repr(str(desktop))+'\n')
        self.write('runtime/wechat_foreground_probe.py','SHARED='+repr(str(desktop))+'\n')
        nested='skills/workflows/not-in-fixed-list/dependencies.json'
        self.write(nested,json.dumps({'files':{str(self.root/self.dep):tool.file_sha(self.root/self.dep)},'rebindHistory':self.history}))
        p=self.plan();package=self.prepare(p)
        for name in ['skills/wechat-messaging/scripts/dependency_maintenance.py','runtime/wechat_foreground_probe.py',nested]:self.assertIn(name,p['baseline'])
        self.assertNotIn(str(desktop),(package/'patches/runtime/wechat_foreground_probe.py').read_text())
        data=json.loads((package/'patches'/nested).read_text())
        self.assertEqual(data['files'][str(self.root/self.dep)],tool.file_sha(package/'patches'/self.dep));self.assertEqual(data['rebindHistory'],self.history)
    def test_frozen_defaults_are_audited_and_wrapper_injected_without_core_changes(self):
        frozen='skills/.daily-jinsha-reports-core/scripts/build_reports.mjs'
        raw='const customer="/Users/ddt/work/臻肆/报表/客户表最新.xlsx";\n'
        self.write(frozen,raw);self.write('skills/.daily-jinsha-reports-core/BASELINE.md','frozen original rule')
        self.write(tool.WRAPPER_FILE,"import { assertFrozenCoreHashes, assertInternalInvocation, assertProductionConfig, assertStagePermission } from './business_workflow_policy.mjs';\nconst build=runBuildReports({receipt:c.downloadReceipt,buildReceipt:c.buildReceipt,outputDir:c.outputDir,filenameSuffix:'',titleSuffix:''});\n")
        before=tool.file_sha(self.root/frozen);p=self.plan();package=self.prepare(p)
        self.assertNotIn(frozen,p['baseline']);self.assertEqual(tool.file_sha(self.root/frozen),before)
        self.assertIn('skills/.daily-jinsha-reports-core/BASELINE.md',p['coverage']['frozenHashes'])
        patched=(package/'patches'/tool.WRAPPER_FILE).read_text()
        for field in ['customer','meituanReference','taobaoTemplate']:self.assertIn(field+':path.join(FIXED.outputRoot,',patched)
        self.assertTrue(any(r['category']=='frozen-opaque-default' for r in p['coverage']['references']))
    def test_actual_shared_inspector_is_clean_against_projected_candidate_tree(self):
        import importlib.util
        from unittest.mock import patch
        project=self.root.parent/'projected';shared=project/'skills/wechat-messaging';(shared/'scripts').mkdir(parents=True)
        actual=Path(tool.__file__).resolve().parents[1]/'skills/wechat-messaging/scripts'
        mandatory=['dependency_maintenance.py','heartbeat_recovery.py','desktop_adapter.py','policy_registration.py','egress_policy.py']
        for name in mandatory:shutil.copy2(actual/name,shared/'scripts'/name)
        old_prefix='/Users/ddt/work/projects/ai_agent/skills/skills/app-controler'
        asset=self.root.parent/'projected-desktop';asset.mkdir();(asset/'wechat_interaction_lock.py').write_text('from pathlib import Path\nLOCK_PATH = Path(__file__).resolve().parents[1] / ".runtime" / "wechat-ui-interaction.lock"\n')
        target='vendor/legacy-app-controler/wechat-desktop-control/scripts'
        config={'schemaVersion':1,'assets':{'desktop-tools':{'source':str(asset),'target':target,'originalArchive':'archive/originals'}},'bindings':{old_prefix:'vendor/legacy-app-controler'}}
        files={'scripts/'+name:tool.file_sha(shared/'scripts'/name) for name in mandatory}
        files[old_prefix+'/wechat-desktop-control/scripts/wechat_interaction_lock.py']=tool.file_sha(asset/'wechat_interaction_lock.py')
        (shared/'dependencies.json').write_text(json.dumps({'schemaVersion':1,'files':files}))
        with patch.object(tool,'load_catalog',return_value=config):
            p=tool.plan(project,self.source);payload=self.root.parent/'projection-payload'
            item=p['assets']['desktop-tools'];tool.copy_snapshot(item['source'],payload/target,item['inventory'])
            candidates=tool.candidate_patches(p,payload)
        for name,raw in candidates.items():file=project/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(raw)
        shutil.copytree(payload/'vendor',project/'vendor')
        spec=importlib.util.spec_from_file_location('projected_actual_dependency_maintenance',shared/'scripts/dependency_maintenance.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        result=module.inspect();self.assertEqual(result['status'],'clean');self.assertEqual(result['sendAttempts'],0)
        self.assertTrue(all(not k.startswith(old_prefix) for k in module.NEW_STORES_ALLOWED_AFTER))
    def test_actual_guard_dispatcher_does_not_accept_drift_or_execute_business(self):
        calls=[]
        def runner(command,**kwargs):
            from types import SimpleNamespace
            calls.append((command,kwargs));value={'status':'drift','ok':True} if 'dependency_maintenance' in command[-1] else {'ok':True}
            return SimpleNamespace(returncode=0,stdout=json.dumps(value),stderr='')
        with patch.object(tool,'installed_coverage',return_value={'ok':True}):result=tool.verify_active(self.root,runner=runner)
        self.assertFalse(result['ok']);self.assertFalse(result['checks']['shared-inspect']['ok']);self.assertEqual(len(calls),5)
        self.assertTrue(all('--execute' not in command and opts['env']['PYTHONDONTWRITEBYTECODE']=='1' for command,opts in calls))
    def test_unknown_active_project_reference_is_reported_not_silently_allowed(self):
        self.write('runtime/new_external.py',"CALLER='/Users/ddt/work/projects/ai_agent/unrelated/script.py'\n")
        coverage=tool.scan_code_coverage(self.root,self.config)
        self.assertTrue(any(r['category']=='unmapped-active-project-reference' and r['path']=='runtime/new_external.py' for r in coverage['references']))
    def test_materialize_only_assets_preserves_runtime_logic_and_state(self):
        original=(self.root/self.guard).read_bytes();cursor=(self.root/'state/cursor.json').read_bytes();package=self.prepare()
        tool.materialize_assets(package,root=self.root,idle_check=lambda _:None)
        self.assertEqual((self.root/self.guard).read_bytes(),original);self.assertEqual((self.root/'state/cursor.json').read_bytes(),cursor)
        self.assertTrue((self.root/('archive/source-before-unification/'+package.name+'/.git/HEAD')).is_file());self.assertFalse((self.root/'.git').exists())
    def test_git_adoption_preserves_all_refs_and_working_files_and_can_undo(self):
        package=self.prepare();before=(self.root/'worker.py').read_bytes();cursor=(self.root/'state/cursor.json').read_bytes()
        tool.adopt_git(package,root=self.root,idle_check=lambda _:None)
        self.assertEqual(self.git(self.root,'for-each-ref','--format=%(refname):%(objectname)'),self.git(self.source,'for-each-ref','--format=%(refname):%(objectname)'))
        self.assertEqual((self.root/'worker.py').read_bytes(),before);self.assertEqual((self.root/'state/cursor.json').read_bytes(),cursor)
        self.assertFalse((self.root/'tracked.py').exists())
        tool.undo_git_adoption(package,root=self.root,idle_check=lambda _:None);self.assertFalse((self.root/'.git').exists())
    def test_new_git_commits_prevent_rollback(self):
        package=self.prepare();tool.adopt_git(package,root=self.root,idle_check=lambda _:None)
        (self.root/'tracked.py').write_text('new local work');self.git(self.root,'add','tracked.py');self.git(self.root,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','new history')
        with self.assertRaisesRegex(ValueError,'new-history'):tool.undo_git_adoption(package,root=self.root,idle_check=lambda _:None)
    def test_private_ignore_required_before_git_adoption(self):
        package=self.prepare();(self.root/'.gitignore').unlink()
        with self.assertRaisesRegex(ValueError,'gitignore'):tool.adopt_git(package,root=self.root,idle_check=lambda _:None)
        self.assertFalse((self.root/'.git').exists())
    def test_changed_payload_cannot_be_materialized(self):
        package=self.prepare();(package/'payload/archive/compat/wechat-windows-driver/client.py').write_text('changed')
        with self.assertRaisesRegex(ValueError,'payload-changed'):tool.materialize_assets(package,root=self.root,idle_check=lambda _:None)
    def test_skill_shim_requires_reviewed_canonical_code(self):
        package=self.prepare()
        with self.assertRaisesRegex(ValueError,'not-reviewed-or-activated'):tool.install_skill_shim(package,root=self.root,idle_check=lambda _:None)
    def test_skill_shim_preserves_original_installation_and_can_undo(self):
        package=self.prepare();tool.materialize_assets(package,root=self.root,idle_check=lambda _:None)
        original=Path(self.config['assets']['installed-skill']['source']);before=tool.snapshot(original)
        shutil.copy2(package/'patches'/self.entry,self.root/self.entry)  # Offline stand-in for reviewed maintenance activation.
        tool.install_skill_shim(package,root=self.root,idle_check=lambda _:None)
        self.assertEqual(tool.snapshot(original),json.loads((package/'prepared.json').read_text())['shimInventory'])
        self.assertIn('export * from',(original/'scripts/entrypoint.mjs').read_text())
        saved=self.root/('archive/installed-skill-original-'+package.name);self.assertEqual(tool.snapshot(saved),before)
        tool.undo_skill_shim(package,root=self.root,idle_check=lambda _:None);self.assertEqual(tool.snapshot(original),before)
    def test_skill_shim_new_write_blocks_rollback(self):
        package=self.prepare();tool.materialize_assets(package,root=self.root,idle_check=lambda _:None)
        shutil.copy2(package/'patches'/self.entry,self.root/self.entry)
        tool.install_skill_shim(package,root=self.root,idle_check=lambda _:None)
        original=Path(self.config['assets']['installed-skill']['source']);(original/'new.json').write_text('new private config')
        with self.assertRaisesRegex(ValueError,'new-writes'):tool.undo_skill_shim(package,root=self.root,idle_check=lambda _:None)
    def test_dirty_source_is_archivable_in_plan_but_preparation_waits_freeze(self):
        (self.source/'tracked.py').write_text('in progress');p=self.plan()
        with self.assertRaisesRegex(ValueError,'not-frozen'):self.prepare(p)
    def test_forged_asset_scope_is_rejected(self):
        p=self.plan();p['assets']['desktop-tools']['source']=str(self.source)
        with self.assertRaisesRegex(ValueError,'scope-invalid'):self.prepare(p)
    def test_source_symlink_keeps_description_without_copying_profile(self):
        profile=self.source.parent/'private-profile';profile.mkdir();(profile/'account.txt').write_text('fixture-private-not-to-copy')
        (self.source/'profile-link').symlink_to(profile)
        self.git(self.source,'add','profile-link');self.git(self.source,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','link fixture')
        package=self.prepare();archive=package/'payload/archive/source-before-unification'
        self.assertFalse((archive/'profile-link').exists());self.assertTrue((archive/'.consolidation-symlinks.json').exists())
        self.assertFalse(any(p.name=='account.txt' for p in (package/'payload').rglob('*')))

if __name__=='__main__':unittest.main()

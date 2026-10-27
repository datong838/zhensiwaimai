import tempfile
import unittest
import subprocess
from pathlib import Path
from audit_source_consolidation import audit,protected


class SourceConsolidationTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.base=Path(self.t.name);self.source=self.base/'source';self.source.mkdir();self.runtime=self.base/'runtime';self.runtime.mkdir()
        self.git('init','-q');self.write('same.py','one');self.write('different.py','old');self.write('archive-only.md','preserve');self.write('.gitignore','state/\n')
        self.git('add','.');self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture')
        (self.runtime/'same.py').write_text('one');(self.runtime/'different.py').write_text('live')
        self.write('state/unknown.json','{"state":"unknown"}')
    def git(self,*args):return subprocess.check_output(['git','-C',str(self.source),*args])
    def write(self,name,text):
        p=self.source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    def test_only_inventory_and_live_difference_preserved(self):
        before=(self.runtime/'different.py').read_bytes();result=audit(self.source,self.runtime)
        self.assertEqual(result['counts'],{'source-only':2,'review-difference':1,'same':1})
        self.assertEqual((self.runtime/'different.py').read_bytes(),before)
        self.assertFalse((self.runtime/'.git').exists());self.assertEqual(result['ignoredEntryCount'],1)
    def test_uncommitted_code_retained_in_report(self):
        self.write('same.py','new code');self.write('untracked.py','new file')
        result=audit(self.source,self.runtime)
        self.assertIn('same.py',result['uncommittedTracked']);self.assertIn('untracked.py',result['untracked'])
    def test_production_data_classified_never_for_overwrite(self):
        for p in ['state/cursor.json','runtime/state/daemon.json','x/.runtime/marker.json','node_modules/pkg/file','data/video/a','archive/source/.git/config','.env.production']:
            self.assertTrue(protected(p))
    def test_external_code_runtime_and_profile_are_separate(self):
        self.write('paths.py',"a='/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/wechat-desktop-control/scripts/wechat_interaction_lock.py'\nb='/Users/ddt/.codex-runtimes/runtime/node_modules/playwright'\nc='/Users/ddt/Library/Application Support/AOS Background Chrome'\n")
        self.git('add','paths.py')
        rows=audit(self.source,self.runtime)['externalReferences']
        self.assertEqual({r['category'] for r in rows},{'external-project-code-review','standard-runtime','browser-profile-do-not-copy'})
        self.assertTrue(protected('skills/wechat-messaging/dependencies.json'))
    def test_symlink_is_reviewed_without_following(self):
        (self.runtime/'same.py').unlink();(self.runtime/'same.py').symlink_to('/nonexistent/outside')
        result=audit(self.source,self.runtime);self.assertEqual(result['counts']['symlink-review'],1)

if __name__=='__main__':unittest.main()

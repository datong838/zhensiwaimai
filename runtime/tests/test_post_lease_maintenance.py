import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import maintain_post_leases_20261028 as subject
import post_lease_file


class PostMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.evidence=self.root/'evidence';self.evidence.mkdir()
        for name,value in [('ROOT',self.root),('EVIDENCE',self.evidence)]:
            p=patch.object(subject,name,value);p.start();self.addCleanup(p.stop)
        baseline=[]
        for post in subject.POSTS:
            folder=self.root/'skills/posts'/post;(folder/'scripts').mkdir(parents=True)
            (folder/'SKILL.md').write_bytes(b'unchanged')
            (folder/'scripts/lease.mjs').write_bytes(b'candidate')
            manifest={'schemaVersion':1,'authorizationRef':'existing','files':{
                'SKILL.md':subject.sha(b'unchanged'),'scripts/lease.mjs':subject.sha(b'original')}}
            data=(json.dumps(manifest)+'\n').encode();(folder/'dependencies.json').write_bytes(data)
            backup=self.evidence/'originals/skills/posts'/post;(backup/'scripts').mkdir(parents=True)
            (backup/'dependencies.json').write_bytes(data);(backup/'scripts/lease.mjs').write_bytes(b'original')
            baseline.append({'post':post,'originalManifestSha256':subject.sha(data)})
        (self.evidence/'before-install.json').write_text(json.dumps({'posts':baseline}))
        for relative in [*subject.ADDITIONS.values(),subject.CONTRACT]:
            p=self.root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'new-shared-source')
        backup=self.evidence/'originals'/subject.CONTRACT;backup.parent.mkdir(parents=True);backup.write_bytes(b'old-contract')
    def reviewed(self):
        plan=subject.prepare();(self.evidence/'review.json').write_text(json.dumps(plan))
        (self.evidence/'preinstall-tests.json').write_text(json.dumps({'ok':True,'sourceDigests':plan['sourceDigests']}))
        return plan
    def apply(self,result=0):
        with patch.object(post_lease_file,'read_owner',return_value=None),patch.object(subject.subprocess,'run',return_value=SimpleNamespace(returncode=result,stdout='fixture-only',stderr='')):
            return subject.apply_reviewed('fixture-node-never-executed')
    def test_review_only_changes_lease_hash_and_two_registered_dependencies(self):
        plan=self.reviewed();self.assertEqual(len(plan['manifestChanges']),4)
        for c in plan['manifestChanges']:
            self.assertEqual(c['candidate']['authorizationRef'],'existing')
            self.assertEqual(c['candidate']['files']['SKILL.md'],subject.sha(b'unchanged'))
            self.assertEqual(set(c['candidate']['files']),{'SKILL.md','scripts/lease.mjs',*subject.ADDITIONS})
    def test_unrelated_source_drift_blocks_prepare(self):
        (self.root/'skills/posts/taobao-brand-post/SKILL.md').write_bytes(b'drift')
        with self.assertRaisesRegex(ValueError,'unrelated-drift'):subject.prepare()
    def test_original_manifest_change_blocks_prepare(self):
        (self.root/'skills/posts/taobao-brand-post/dependencies.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'original-manifest-changed'):subject.prepare()
    def test_source_change_after_review_blocks_apply(self):
        self.reviewed();(self.root/'runtime/post_lease_file.py').write_bytes(b'changed-after-tests')
        with self.assertRaisesRegex(ValueError,'review-no-longer-matches'):self.apply()
    def test_untested_candidate_blocks_apply(self):
        self.reviewed();(self.evidence/'preinstall-tests.json').write_text('{"ok":false}')
        with self.assertRaisesRegex(ValueError,'tested-source-mismatch'):self.apply()
    def test_live_owner_blocks_without_writing_manifests(self):
        self.reviewed();before=(self.root/'skills/posts/taobao-brand-post/dependencies.json').read_bytes()
        with patch.object(post_lease_file,'read_owner',return_value={'pid':os.getpid()}):
            with self.assertRaisesRegex(ValueError,'active-or-unconfirmed-owner'):subject.apply_reviewed('not-executed')
        self.assertEqual((self.root/'skills/posts/taobao-brand-post/dependencies.json').read_bytes(),before)
    def test_failed_original_gate_rolls_back_matching_sources_and_manifests(self):
        self.reviewed()
        with self.assertRaisesRegex(ValueError,'original-post-gate-failed'):self.apply(result=1)
        for post in subject.POSTS:
            folder=self.root/'skills/posts'/post;backup=self.evidence/'originals/skills/posts'/post
            self.assertEqual((folder/'dependencies.json').read_bytes(),(backup/'dependencies.json').read_bytes())
            self.assertEqual((folder/'scripts/lease.mjs').read_bytes(),b'original')
        self.assertEqual((self.root/subject.CONTRACT).read_bytes(),b'old-contract')
    def test_success_keeps_original_gates_and_records_exact_changes(self):
        self.reviewed();result=self.apply()
        self.assertTrue(result['ok']);self.assertEqual(len(result['originalGates']),4)
        self.assertTrue((self.evidence/'install-receipt.json').is_file())


if __name__=='__main__':unittest.main()

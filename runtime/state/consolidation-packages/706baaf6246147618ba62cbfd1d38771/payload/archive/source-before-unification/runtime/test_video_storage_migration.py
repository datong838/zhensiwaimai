"""Real video dedup/publish orchestration against copied fixture data; no UI or publishing."""
import hashlib
import importlib
import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import business_storage as storage
import migrate_business_storage as migration

SCRIPTS=Path(__file__).resolve().parents[1]/'skills/workflows/daily-wechat-video-publish/scripts'


class VideoStorageMigrationTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        base=Path(self.t.name).resolve();self.repo=base/'repo';(self.repo/'runtime').mkdir(parents=True)
        self.old=base/'external-video';self.old.mkdir()
        (self.repo/'runtime/business_storage_catalog.json').write_text(json.dumps({'schemaVersion':1,'objects':{'video-assets':{'legacy':str(self.old),'target':'data/video'}}}))
        sys.path.insert(0,str(SCRIPTS));self.addCleanup(lambda:sys.path.remove(str(SCRIPTS)))
        self.paths=importlib.import_module('lib.storage_paths')
        mockroot=patch.object(self.paths,'REPO_ROOT',self.repo);mockroot.start()
        def restore_roots():
            mockroot.stop()
            importlib.reload(self.history);importlib.reload(self.checkpoint)
        self.addCleanup(restore_roots)
        self.history=importlib.import_module('lib.history_index');self.checkpoint=importlib.import_module('lib.checkpoint')
        self.source={'group':'fixture-group','sender':'fixture-sender','messageTime':'2026-10-25T19:30:00+08:00','coverText':'fixture-cover','duration':30}
    def migrate(self):
        p=migration.make_plan(self.repo,['video-assets'])
        migration.apply_plan(p,root=self.repo,idle_check=lambda _:None)
        importlib.reload(self.history);importlib.reload(self.checkpoint)
        spec=importlib.util.spec_from_file_location('fixture_video_workflow',SCRIPTS/'workflow_executor.py')
        self.workflow=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.workflow)
        return storage.business_path('video-assets',root=self.repo)
    def test_old_sha_key_matches_relocated_video_without_changing_index(self):
        sha=hashlib.sha256(b'fixture-video-content').hexdigest()
        old={'source':self.source,'sha256':sha,'localFile':str(self.old/'old-video.mp4')}
        self.history.record_entry(old,run_id='20261025-01',state='submitted',path=self.old/'processed_index.json')
        before=(self.old/'processed_index.json').read_bytes();newroot=self.migrate()
        moved=dict(old,localFile=str(newroot/'old-video.mp4'))
        self.assertEqual(self.history.DEFAULT_INDEX,newroot/'processed_index.json')
        self.assertTrue(self.history.is_processed(moved))
        self.assertEqual((newroot/'processed_index.json').read_bytes(),before)
        self.assertEqual((self.old/'processed_index.json').read_bytes(),before)
    def test_old_composite_key_matches_after_root_move(self):
        old={'source':self.source,'localFile':str(self.old/'old-video.mp4')}
        self.history.record_entry(old,run_id='20261025-01',state='downloaded',path=self.old/'processed_index.json')
        newroot=self.migrate()
        self.assertTrue(self.history.is_processed(dict(old,localFile=str(newroot/'old-video.mp4'))))
    def test_legacy_checkpoint_keeps_last_cutoff(self):
        self.checkpoint.update_checkpoint('fixture-group','fixture-sender','2026-10-25T19:30:00+08:00','20261025-01',path=self.old/'scan_checkpoint.json')
        original=(self.old/'scan_checkpoint.json').read_bytes();newroot=self.migrate()
        self.assertEqual(self.checkpoint.CHECKPOINT_FILE,newroot/'scan_checkpoint.json')
        self.assertEqual(self.checkpoint.get_last_cutoff('fixture-group','fixture-sender'),'2026-10-25T19:30:00+08:00')
        self.assertEqual((newroot/'scan_checkpoint.json').read_bytes(),original)
    def test_old_submitted_and_verified_run_is_not_published_again(self):
        run=self.old/'runs/fixture-enterprise/fixture-group/20261025-01';run.mkdir(parents=True)
        row={'id':'fixture-video','source':self.source,'localFile':str(self.old/'old-video.mp4'),'sha256':'a'*64,'caption':'fixture-caption','state':'submitted','platforms':{'douyin':{'state':'submitted'},'kuaishou':{'state':'verified'},'channels':{'state':'submitted'}}}
        raw=json.dumps(row)+'\n';(run/'candidates.jsonl').write_text(raw)
        (run/'run.json').write_text(json.dumps({'enterprise':'fixture-enterprise','group':'fixture-group','runId':'20261025-01'}))
        self.migrate();adapter=Mock(side_effect=AssertionError('publishing is forbidden in migration fixture'))
        args=SimpleNamespace(run_id='20261025-01',enterprise='fixture-enterprise',group='fixture-group',platform='all',confirm_publish=True)
        output=StringIO()
        with patch.object(self.workflow,'_publish_one',adapter),redirect_stdout(output):result=self.workflow.cmd_publish(args)
        self.assertEqual(result,0);self.assertEqual(json.loads(output.getvalue())['published'],0)
        adapter.assert_not_called();self.assertEqual((run/'candidates.jsonl').read_text(),raw)
    def test_mapping_and_namespaced_checkpoint_are_preserved(self):
        mapping=self.old/'微信群-店铺名-店铺地址.xlsx'
        with zipfile.ZipFile(mapping,'w') as z:
            z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="map" r:id="r1"/></sheets></workbook>')
            z.writestr('xl/_rels/workbook.xml.rels','<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>')
            z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row><c r="A1"><v>fixture-group</v></c><c r="B1"><v>fixture-shop</v></c><c r="C1"><v>fixture-address</v></c></row></sheetData></worksheet>')
        cp=self.old/'state/fixture-enterprise/fixture-group/checkpoint.json';cp.parent.mkdir(parents=True);cp.write_text('{"lastMessageTime":"2026-10-25T19:30:00+08:00"}')
        mapping_sha=hashlib.sha256(mapping.read_bytes()).hexdigest();newroot=self.migrate()
        self.assertEqual(self.workflow.MAPPING,newroot/mapping.name)
        self.assertEqual(self.workflow.read_mapping(self.workflow.MAPPING),{'fixture-group':{'shop':'fixture-shop','address':'fixture-address'}})
        self.assertEqual(hashlib.sha256(self.workflow.MAPPING.read_bytes()).hexdigest(),mapping_sha)
        self.assertEqual((newroot/cp.relative_to(self.old)).read_bytes(),cp.read_bytes())

if __name__=='__main__':unittest.main()

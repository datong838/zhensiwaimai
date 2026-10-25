import json
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from PIL import Image
import phone_executor as p

class SafetyTests(unittest.TestCase):
    def test_original_label_decoration(self):
        self.assertEqual(len(p.find_exact([{'text':'• 原图'}],'原图')),1)
        self.assertEqual(p.find_exact([{'text':'非原图'}],'原图'),[])
        self.assertEqual(p.find_exact([{'text':'原图说明'}],'原图'),[])
    def test_weak_thumbnail_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'image.png';Image.new('RGB',(1080,2340),'white').save(f)
            for distance,accepted in [(31.741,False),(9.916,True)]:
                with patch.object(p,'fingerprint_distance',side_effect=lambda *_:distance),patch.object(p,'gallery_candidates',return_value=[((0,0,270,270),(242,246))]):
                    if accepted:self.assertEqual(p.select_target_thumbnail(f,f)[1],9.916)
                    else:
                        with self.assertRaises(p.StopRun):p.select_target_thumbnail(f,f)

    def test_phone_replay_needs_explicit_authorization(self):
        result=p.run_executor(SimpleNamespace(phone_only_replay=True,execute=True))
        self.assertFalse(result['ok']);self.assertEqual(result['sendAttempts'],0)
        self.assertEqual(result['reason'],'phone-replay-authorization-missing')

    def test_repeat_first_blocks_later_default_send(self):
        with tempfile.TemporaryDirectory() as d:
            desktop=dict(dataDate='2026-09-07',runId='first',sha256='test')
            p.claim_send_once(desktop,Path(d),authorized_repeat_id='11111111-1111-4111-8111-111111111111')
            with self.assertRaises(p.StopRun):
                p.claim_send_once(desktop,Path(d))

    def test_exact_group(self):
        # 2026-10-20 群改为运营群：夹具一律从 TARGET_GROUP 派生，避免改群名再破测试。
        g = p.TARGET_GROUP
        for name in [g, g + '（18）', g + '（18）💬', g + '（18）C~', g + ' Q']:
            self.assertTrue(p.exact_group_title(name, g))
        for name in [g + '2', g + '-临时', g + '（分群）', g + '（18）临时', g[:-1]]:
            self.assertFalse(p.exact_group_title(name, g))

    def test_current_wechat_search_sections_without_network_heading(self):
        entries=[{'x':119,'y':318,'text':'最常使用'},
                 {'x':494,'y':452,'text':p.TARGET_GROUP + '（18）'},
                 {'x':82,'y':623,'text':'群聊'},
                 {'x':340,'y':724,'text':'创建新的群聊'},
                 {'x':121,'y':925,'text':'聊天记录'}]
        self.assertEqual(len(p.group_search_candidates(entries,p.TARGET_GROUP)),1)

    def test_training_cannot_send(self):
        result=p.run_executor(SimpleNamespace(train_phone=True,execute=True))
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'],'training-cannot-send')
        self.assertEqual(result['sendAttempts'],0)

    def test_send_once_persists_across_runs(self):
        with tempfile.TemporaryDirectory() as d:
            desktop=dict(dataDate='2026-09-03',runId='first',sha256='test')
            marker=p.claim_send_once(desktop,Path(d))
            self.assertTrue(marker.exists())
            self.assertIn(__import__('hashlib').sha256(p.TARGET_GROUP.encode()).hexdigest()[:12], marker.name)
            self.assertNotEqual(p.AUTHORIZATION, 'zhensi-test-main-wechat-v1')
            with self.assertRaises(p.StopRun):
                p.claim_send_once(desktop|dict(runId='second'),Path(d))

    def test_receipt_rejections(self):
        with tempfile.TemporaryDirectory() as d:
            image=Path(d)/'image.png'; Image.new('RGB',(1500,900),'white').save(image)
            file=Path(d)/'desktop.json'; now=time.time()*1000
            valid=dict(ok=True,executor='desktop',file=str(image),width=1500,height=900,
                sha256=p.sha256_file(image),stores=['店']*10,revenues=list(range(10,0,-1)),
                page=1,pageSize=10,runId='11111111-1111-4111-8111-111111111111',
                startedAt=now,deadlineAt=now+170000,
                dataDate=(datetime.now(ZoneInfo('Asia/Shanghai')).date()-timedelta(days=1)).isoformat())
            file.write_text(json.dumps(valid)); p.load_receipt(file)
            # Native desktop delivery follows its original live owner, not age.
            file.write_text(json.dumps(valid | dict(startedAt=now-600000,deadlineAt=now-1)))
            p.load_receipt(file, enforce_expiry=False)
            file.write_text(json.dumps(valid | dict(sha256='invalid')))
            with self.assertRaises(p.StopRun):p.load_receipt(file, enforce_expiry=False)
            for change in [dict(dataDate='2000-01-01'),dict(deadlineAt=now-1),dict(runId=''),dict(width=1600),dict(revenues=list(range(10))),dict(pageSize=20),dict(ok=False),dict(sha256='x')]:
                with self.subTest(change=change):
                    file.write_text(json.dumps(valid|change))
                    with self.assertRaises(p.StopRun): p.load_receipt(file)

    def test_separately_authorized_repeat_is_once(self):
        with tempfile.TemporaryDirectory() as d:
            desktop=dict(dataDate='2026-09-03',runId='first',sha256='test')
            original=p.claim_send_once(desktop,Path(d))
            repeat_id='22222222-2222-4222-8222-222222222222'
            repeat=p.claim_send_once(desktop,Path(d),authorized_repeat_id=repeat_id)
            self.assertNotEqual(original,repeat)
            with self.assertRaises(p.StopRun):p.claim_send_once(desktop|dict(runId='second'),Path(d),authorized_repeat_id=repeat_id)
            with self.assertRaises(p.StopRun):p.claim_send_once(desktop,Path(d))
            with self.assertRaises(p.StopRun):p.claim_send_once(desktop,Path(d),authorized_repeat_id='../invalid')

if __name__=='__main__': unittest.main()

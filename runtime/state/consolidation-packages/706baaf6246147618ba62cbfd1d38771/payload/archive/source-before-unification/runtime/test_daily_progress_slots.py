import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import daily_progress as progress

class LatestSlotTests(unittest.TestCase):
    def row(self, now, success, fixed=True):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            skill = {'name':'example','dev_state':'active','enabled':True,'earliest_hour':13}
            if fixed:
                skill['schedule_times'] = ['13:00','15:00','17:00','18:30']
            (root/'manifest.json').write_text(json.dumps({'skills':[skill]}))
            (root/'last_success.json').write_text(json.dumps({'example':success}))
            with patch.object(progress,'MANIFEST',root/'manifest.json'), patch.object(progress,'STATE',root), patch.object(progress,'RUN_HISTORY',root):
                return progress.build(dt.datetime.fromisoformat(now))['rows'][0]
    def test_old_success_does_not_cover_later_slots(self):
        for hour in ['15:00','17:00','18:55']:
            row=self.row('2026-10-24T'+hour,'2026-10-24T13:10:00')
            self.assertTrue(row['due']); self.assertFalse(row['done'])
    def test_current_slot_success(self):
        self.assertTrue(self.row('2026-10-24T18:55','2026-10-24T18:31:00')['done'])
    def test_before_first_slot(self):
        row=self.row('2026-10-24T12:55','2026-10-24T12:30:00')
        self.assertFalse(row['done']);self.assertFalse(row['due'])
    def test_single_slot_behavior_preserved(self):
        self.assertTrue(self.row('2026-10-24T18:55','2026-10-24T13:10:00',False)['done'])

if __name__=='__main__': unittest.main()

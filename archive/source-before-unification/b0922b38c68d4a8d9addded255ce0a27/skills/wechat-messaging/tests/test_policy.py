import sys,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from executor import runtime_gate
from contract import Rejected

class PolicyTests(unittest.TestCase):
    def test_offline_denies_all_execute(self):
        with patch('executor.verify_dependencies'),patch('executor.read_json',return_value={'mode':'offline'}):
            with self.assertRaisesRegex(Rejected,'runtime-offline'):runtime_gate({}, {})
    def test_other_group_cannot_use_test_scope(self):
        policy={'mode':'acceptance','groupName':'臻肆测试群','requestDigests':[]}
        with patch('executor.verify_dependencies'),patch('executor.read_json',return_value=policy):
            with self.assertRaisesRegex(Rejected,'acceptance-scope'):runtime_gate({'groupName':'生产群'}, {})
    def test_hash_drift_denied_first(self):
        with patch('executor.verify_dependencies',side_effect=Rejected('dependency-drift')),patch('executor.read_json') as read:
            with self.assertRaisesRegex(Rejected,'dependency-drift'):runtime_gate({}, {})
            read.assert_not_called()

if __name__=='__main__':unittest.main()

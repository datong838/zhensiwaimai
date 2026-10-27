import importlib.util,types,unittest,sys
from pathlib import Path
root=Path.cwd();p=root/'runtime/tests/test_new_store_inspection_recovery.py'
spec=importlib.util.spec_from_file_location('before_tests',p);tests=importlib.util.module_from_spec(spec);spec.loader.exec_module(tests)
old=[]
for kind,_,flow in tests.FLOWS:
 m=types.ModuleType('old_'+kind);m.__file__=str(root/f'skills/workflows/daily-new-stores-{kind}-audit-to-wechat/scripts/{kind}_daily.py')
 exec(compile((root/f'runtime/state/inspection-recovery-20261028/original-{kind}-daily.py').read_text(),m.__file__,'exec'),m.__dict__)
 old.append((kind,m,flow))
tests.FLOWS=old
suite=unittest.TestSuite(tests.InspectionRecoveryTests(name) for name in ['test_busy_never_retries_resets_sends_or_finishes','test_busy_single_target_is_never_completed','test_search_timeout_recovers_once_before_one_delivery'])
r=unittest.TextTestRunner(verbosity=2).run(suite);sys.exit(0 if r.wasSuccessful() else 1)

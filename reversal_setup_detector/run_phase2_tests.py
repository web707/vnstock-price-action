import datetime,json,platform,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));results=[]
class LoggedResult(unittest.TextTestResult):
    def addSuccess(self,t):super().addSuccess(t);results.append(dict(test=t.id(),status='PASS'))
    def addFailure(self,t,e):super().addFailure(t,e);results.append(dict(test=t.id(),status='FAIL'))
    def addError(self,t,e):super().addError(t,e);results.append(dict(test=t.id(),status='ERROR'))
    def addSkip(self,t,r):super().addSkip(t,r);results.append(dict(test=t.id(),status='SKIP',reason=r))
print('Layer 3 Phase 2 + Phase 1 regression. AT08/AT09; context look-ahead; timestamp boundaries; real ACTIVE evidence.',flush=True)
print('UTC',datetime.datetime.now(datetime.timezone.utc).isoformat(),'Python',sys.version,'Platform',platform.platform(),flush=True)
suite=unittest.defaultTestLoader.discover(str(ROOT/'reversal_setup_detector/tests'),top_level_dir=str(ROOT))
r=unittest.TextTestRunner(verbosity=2,resultclass=LoggedResult).run(suite)
(ROOT/'reports/layer3_phase2/test_results.json').write_text(json.dumps(results,indent=2))
print(f'RESULT tests={r.testsRun} passed={r.testsRun-len(r.failures)-len(r.errors)-len(r.skipped)} failures={len(r.failures)} errors={len(r.errors)} skipped={len(r.skipped)}',flush=True)
sys.exit(not r.wasSuccessful())

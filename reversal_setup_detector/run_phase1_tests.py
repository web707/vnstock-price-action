import datetime,json,platform,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
class LoggedResult(unittest.TextTestResult):
    def addSuccess(self,test):super().addSuccess(test);results.append(dict(test=test.id(),status='PASS'))
    def addFailure(self,test,err):super().addFailure(test,err);results.append(dict(test=test.id(),status='FAIL'))
    def addError(self,test,err):super().addError(test,err);results.append(dict(test=test.id(),status='ERROR'))
    def addSkip(self,test,reason):super().addSkip(test,reason);results.append(dict(test=test.id(),status='SKIP',reason=reason))
results=[]
print('Layer 3 Phase 1: candle morphology / red triplets / calendar gaps ONLY',flush=True)
print('UTC',datetime.datetime.now(datetime.timezone.utc).isoformat(),'Python',sys.version,'Platform',platform.platform(),flush=True)
print('AT01–AT07 and AT21. Future phases AT08–AT20, AT22 NOT IMPLEMENTED.',flush=True)
suite=unittest.defaultTestLoader.discover(str(ROOT/'reversal_setup_detector/tests'),top_level_dir=str(ROOT))
r=unittest.TextTestRunner(verbosity=2,resultclass=LoggedResult).run(suite)
(ROOT/'reports/layer3_phase1/test_results.json').write_text(json.dumps(results,indent=2))
print(f'RESULT tests={r.testsRun} passed={r.testsRun-len(r.failures)-len(r.errors)-len(r.skipped)} failures={len(r.failures)} errors={len(r.errors)} skipped={len(r.skipped)}',flush=True)
sys.exit(not r.wasSuccessful())

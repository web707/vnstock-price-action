"""Run full acceptance AT01-AT22 + Phase4 tests. Produces actual stdout log."""
import sys,unittest,platform
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
loader=unittest.TestLoader();suite=unittest.TestSuite()
for module in ('reversal_setup_detector.tests.test_phase1',
               'reversal_setup_detector.tests.test_phase2',
               'reversal_setup_detector.tests.test_phase3',
               'reversal_setup_detector.tests.test_phase4'):
    suite.addTests(loader.loadTestsFromName(module))
print('Layer3 PHASE4 regression+AT19,AT20,AT22 | AT19/AT20/AT22 SYNTHETIC | real replay REAL_SNAPSHOT',flush=True)
print('RUN START UTC',datetime.now(timezone.utc).isoformat(),'Python',sys.version.split()[0],platform.platform(),flush=True)
res=unittest.TextTestRunner(verbosity=2,stream=sys.stdout).run(suite)
print('RESULT tests={} passed={} failures={} errors={} skipped={}'.format(res.testsRun,
    res.testsRun-len(res.failures)-len(res.errors)-len(res.skipped),len(res.failures),len(res.errors),len(res.skipped)),flush=True)
print('RUN END UTC',datetime.now(timezone.utc).isoformat(),flush=True)
sys.exit(0 if res.wasSuccessful() else 1)

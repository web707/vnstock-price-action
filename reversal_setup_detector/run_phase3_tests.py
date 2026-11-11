"""Full Phase1/2 regression plus Phase3 acceptance and replay tests; real stdout log."""
import sys,unittest,platform
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
loader=unittest.TestLoader()
suite=unittest.TestSuite()
for module in ('reversal_setup_detector.tests.test_phase1',
               'reversal_setup_detector.tests.test_phase2',
               'reversal_setup_detector.tests.test_phase3'):
    suite.addTests(loader.loadTestsFromName(module))
print('Layer3 Phase3 | baseline Phase1/Phase2 regression + AT10-AT18 synthetic + real-data audit',flush=True)
print('RUN START UTC',datetime.now(timezone.utc).isoformat(),'Python',sys.version.split()[0],platform.platform(),flush=True)
print('No SQL writes, no LONG_SETUP export. Phase3 configs versioned. Calendar UNVERIFIED.',flush=True)
res=unittest.TextTestRunner(verbosity=2,stream=sys.stdout).run(suite)
print('RESULT tests={} passed={} failures={} errors={} skipped={}'.format(
    res.testsRun,res.testsRun-len(res.failures)-len(res.errors)-len(res.skipped),
    len(res.failures),len(res.errors),len(res.skipped)),flush=True)
print('RUN END UTC',datetime.now(timezone.utc).isoformat(),flush=True)
sys.exit(0 if res.wasSuccessful() else 1)

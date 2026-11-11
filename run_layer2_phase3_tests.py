import datetime,platform,sys,unittest
import pandas as pd
print('UTC:',datetime.datetime.now(datetime.timezone.utc).isoformat(),flush=True)
print('Python:',sys.version,'Platform:',platform.platform(),'pandas:',pd.__version__,flush=True)
suite=unittest.TestSuite()
for folder in ('phase1_tests','phase2_tests','phase3_tests'):
    suite.addTests(unittest.defaultTestLoader.discover(folder,top_level_dir='.'))
r=unittest.TextTestRunner(verbosity=2).run(suite)
print('RESULT tests=%s passed=%s failures=%s errors=%s skipped=%s'%(r.testsRun,r.testsRun-len(r.failures)-len(r.errors)-len(r.skipped),len(r.failures),len(r.errors),len(r.skipped)),flush=True)
sys.exit(not r.wasSuccessful())

"""Run regression + Phase 2 tests, preserving genuine unittest stdout/stderr."""
import sys,unittest,platform
import pandas as pd
from datetime import datetime,timezone
if __name__=='__main__':
 print('QTA Layer 2 Phase 2 test execution',flush=True)
 print('UTC:',datetime.now(timezone.utc).isoformat(),flush=True)
 print('Python:',sys.version,flush=True)
 print('Platform:',platform.platform(),'pandas:',pd.__version__,flush=True)
 suite=unittest.TestSuite()
 loader=unittest.TestLoader()
 for directory in ['phase1_tests','phase2_tests']:
  suite.addTests(loader.discover(directory,top_level_dir='.'))
 result=unittest.TextTestRunner(verbosity=2).run(suite)
 sys.exit(not result.wasSuccessful())

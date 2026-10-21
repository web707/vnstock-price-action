"""Lightweight isolated tests for the all-symbol CSV universe and audit logic."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import pandas as pd
from audit_all_symbols import audit_frame, audit_repository
from sync_all_symbols import plan, main

class AllSymbolsWorkflowTests(unittest.TestCase):
    def test_seed_selection_includes_all_three_exchanges(self):
        symbols = plan()
        self.assertGreater(len(symbols), 1000)
        self.assertEqual({s['exchange'].upper() for s in symbols}, {'HOSE','HNX','UPCOM'})
        self.assertTrue(all(s['security_type'] == 'EQUITY' for s in symbols))

    def test_no_network_or_db_on_dry_run(self):
        self.assertEqual(main(['--limit','2']), 0)

    def test_missing_symbols_reported_as_no_data(self):
        class FakeRepo:
            def get_symbols_summary(self): return []
            def query_historical_prices(self, sym): return pd.DataFrame()
        with TemporaryDirectory() as d:
            seed = Path(d) / 'symbols.csv'
            pd.DataFrame([{'symbol':'AAA','exchange':'HOSE'}]).to_csv(seed,index=False)
            rows = audit_repository(FakeRepo(), Path(d)/'report.csv', seed)
            self.assertEqual(rows[0]['status'], 'NO_DATA')
            self.assertTrue((Path(d)/'report.csv').exists())

    def test_invalid_ohlcv_detected(self):
        frame = pd.DataFrame([{'TRADE_DATE':'2026-10-01','OPEN_PRICE':10,'HIGH_PRICE':9,'LOW_PRICE':8,'CLOSE_PRICE':11,'VOLUME':50,'ADJ_CLOSE':11}])
        self.assertEqual(audit_frame(frame)['status'], 'INVALID')

if __name__ == '__main__':
    unittest.main()

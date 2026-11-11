from pathlib import Path
import unittest
import pandas as pd
from structure_builder_sfs.phase3 import StructureEngine,build_structures,semantic
ROOT=Path(__file__).resolve().parents[1]
END=pd.Timestamp('2026-10-28 23:59:59',tz='Asia/Ho_Chi_Minh')
class RealReplayTests(unittest.TestCase):
    def check_ticker(self,ticker,count):
        s=pd.read_csv(ROOT/f'reports/layer1_schema/{ticker}.csv');b=pd.read_csv(ROOT/f'reports/layer1/{ticker}_clean.csv')
        full=StructureEngine(s,b);final=full.advance(END);self.assertEqual(final['batch_log']['ever_confirmed'],count)
        replay=StructureEngine(s,b);closes=pd.to_datetime(b.Datetime)+pd.Timedelta(minutes=15)
        for t in closes:
            a=replay.advance(t);e=full.snapshot(t)
            self.assertEqual(a['market_structure_event'].to_dict('records'),e['market_structure_event'].to_dict('records'),str(t))
        confirmed=pd.to_datetime(s.confirmed_at).dt.tz_localize('Asia/Ho_Chi_Minh')
        for fraction in (.25,.5,.75):
            t=closes.iloc[int(len(closes)*fraction)];prefix=build_structures(s[confirmed<=t],b[closes<=t],as_of=t);expected=full.snapshot(t)
            self.assertEqual(prefix['market_structure_event'].to_dict('records'),expected['market_structure_event'].to_dict('records'))
            pd.testing.assert_frame_equal(prefix['market_structure'].drop(columns=['created_at','updated_at']),expected['market_structure'].drop(columns=['created_at','updated_at']))
        if ticker=='HPG':
            r=final['market_structure'];x=r[(r.start_swing_id=='35')&(r.end_swing_id=='38')].iloc[0]
            self.assertEqual(x.status,'UNCLEAR');self.assertTrue(pd.isna(x.confirmed_at));self.assertEqual(x.reason_code,'PROTECTED_LEVEL_VIOLATED_AT_AVAILABILITY')
        print(f'TC15 {ticker}: {len(b)} closed-bar replay cutoffs + 3 truncated-input cutoffs; ever_confirmed={count}',flush=True)
    def test_TC15_HPG(self):self.check_ticker('HPG',10)
    def test_TC15_FPT(self):self.check_ticker('FPT',12)
    def test_TC15_VNM(self):self.check_ticker('VNM',15)
    def test_TC15_VCB(self):self.check_ticker('VCB',15)
    def test_TC15_SSI(self):self.check_ticker('SSI',12)

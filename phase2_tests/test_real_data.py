"""Real archived inputs; no synthetic data substituted in these tests."""
import unittest
from pathlib import Path
import pandas as pd
from structure_builder_sfs.phase2 import build_legs
ROOT=Path(__file__).resolve().parents[1]
ASOF='2026-10-28 23:59:59+07:00'
class RealDataTests(unittest.TestCase):
 def check_ticker(self,ticker):
  d=pd.read_csv(ROOT/f'reports/layer1_schema/{ticker}.csv')
  o=pd.read_csv(ROOT/f'reports/layer1/{ticker}_clean.csv')
  full=build_legs(d,o,as_of=ASOF)['swing_leg']
  self.assertEqual(len(full),len(d)-1)
  self.assertEqual(set(full.classification),{'UNCLASSIFIED'})
  self.assertEqual(full.leg_id.nunique(),len(full))
  points=sorted(set([0,1,len(d)//3,len(d)//2,len(d)-1]))
  for i in points:
   t=pd.Timestamp(d.confirmed_at.iloc[i]).tz_localize('Asia/Ho_Chi_Minh')
   cutoff=pd.to_datetime(d.confirmed_at).dt.tz_localize('Asia/Ho_Chi_Minh')<=t
   bars=pd.to_datetime(o.Datetime)+pd.Timedelta(minutes=15)<=t
   with self.subTest(ticker=ticker,cutoff=str(t)):
    # Future candles/swings in the batch cannot change the point-in-time result.
    a=build_legs(d,o,as_of=t)['swing_leg']
    b=build_legs(d[cutoff],o[bars],as_of=t)['swing_leg']
    pd.testing.assert_frame_equal(a,b)
    c=full[full.available_at<=t].reset_index(drop=True)
    pd.testing.assert_frame_equal(a,c,check_dtype=False)
 def test_HPG(self):self.check_ticker('HPG')
 def test_FPT(self):self.check_ticker('FPT')
 def test_VNM(self):self.check_ticker('VNM')
 def test_VCB(self):self.check_ticker('VCB')
 def test_SSI(self):self.check_ticker('SSI')

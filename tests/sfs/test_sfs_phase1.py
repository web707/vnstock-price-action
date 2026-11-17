import unittest
from dataclasses import replace
import pandas as pd
import numpy as np
from structure_builder_sfs import Config,build_labels

def sample():
 t=pd.date_range('2026-01-05 09:00',periods=8,freq='2h',tz='Asia/Ho_Chi_Minh')
 return pd.DataFrame(dict(swing_id=range(1,9),ticker='HPG',timeframe='15m',swing_type=['HIGH','LOW']*4,extreme_price=[100,90,110,95,105,85,105,85],extreme_time=t,confirmed_at=t+pd.Timedelta(hours=1),atr_at_extreme=2.,source_version='fixture-v1'))
def run(d,**kw):return build_labels(d,as_of=kw.pop('as_of','2026-01-08 00:00+07:00'),**kw)
def labels(r):return r['swing_label'].drop(columns='created_at')

class Phase1Tests(unittest.TestCase):
 def test_TC01_duplicate(self):
  d=sample();r=run(pd.concat([d,d.iloc[[0]]]))
  self.assertEqual(len(r['swing_label']),8);self.assertIn('DUPLICATE_SWING',set(r['audit'].reason_code));self.assertEqual(len(r['raw']),9)
 def test_TC01_conflicting_duplicate(self):
  d=sample();x=d.iloc[[0]].copy();x.extreme_price=999;r=run(pd.concat([d,x]))
  self.assertEqual(sum(r['quarantine'].reason_code=='DUPLICATE_SWING'),2)
 def test_TC02_unconfirmed(self):
  d=sample();r=run(d,as_of=d.confirmed_at.iloc[2]);self.assertEqual(list(r['swing_label'].swing_id),['1','2','3'])
 def test_TC02_future_duplicate_cannot_veto(self):
  d=sample();x=d.iloc[[0]].copy();x.extreme_price=999;x.confirmed_at=d.confirmed_at.iloc[-1]+pd.Timedelta(days=5)
  pd.testing.assert_frame_equal(labels(run(d)),labels(run(pd.concat([d,x]))))
 def test_TC03_extreme_order(self):
  d=sample();d.loc[0,'confirmed_at']=d.confirmed_at.iloc[-1];r=run(d.iloc[::-1])
  self.assertEqual(list(r['swing_label'].swing_id),list(map(str,range(1,9))))
  self.assertTrue((r['swing_label'].available_at==d.confirmed_at.iloc[-1]).all())
 def test_TC04_same_type(self):
  d=sample();d.loc[1,'swing_type']='HIGH';r=run(d)
  self.assertTrue(r['swing_label'].empty);self.assertEqual(len(r['quarantine']),8);self.assertEqual(len(r['raw']),8)
 def test_TC05_labels_references(self):
  r=run(sample())['swing_label'];self.assertEqual(list(r.mechanical_label),['FIRST_HIGH','FIRST_LOW','HH','HL','LH','LL','EQH','EQL']);self.assertEqual(list(r.reference_swing_id.iloc[2:]),['1','2','3','4','5','6'])
 def test_TC06_equal_boundaries(self):
  for delta,expected in [(1,'EQH'),(-1,'EQH'),(1.001,'HH'),(-1.001,'LH')]:
   with self.subTest(delta=delta):
    d=sample().iloc[:3].copy();d.loc[2,'extreme_price']=100+delta;self.assertEqual(run(d)['swing_label'].iloc[-1].mechanical_label,expected)
 def test_TC06_pct_tolerance(self):
  d=sample().iloc[:3].copy();d.extreme_price=[10000,9000,10001];r=run(d,config=replace(Config(),equal_price_pct=.001))['swing_label'];self.assertEqual(r.iloc[-1].price_tolerance,10.001)
 def test_invalid_values(self):
  for field,value,code in [('swing_id',None,'INVALID_SWING_ID'),('swing_type','MID','INVALID_SWING_TYPE'),('extreme_price',0,'INVALID_PRICE'),('extreme_price',np.inf,'INVALID_PRICE'),('extreme_time','bad','INVALID_TIMESTAMP'),('confirmed_at','bad','INVALID_TIMESTAMP')]:
   with self.subTest(field=field,value=value):
    d=sample();d[field]=d[field].astype(object);d.loc[0,field]=value;self.assertIn(code,set(run(d)['quarantine'].reason_code))
 def test_missing_atr(self):
  for value in [None,0,-1,np.nan,np.inf]:
   d=sample();d.atr_at_extreme=value;r=run(d);self.assertTrue(r['validated'].atr_at_extreme.isna().all());self.assertEqual(len(r['swing_label']),8)
 def test_ambiguous_order(self):
  d=sample();d.loc[1,'extreme_time']=d.extreme_time.iloc[0];r=run(d);self.assertTrue(r['swing_label'].empty);self.assertIn('DATA_ORDER_AMBIGUOUS',set(r['quarantine'].reason_code))
 def test_mixed_context(self):
  for field in ['ticker','source_version']:
   d=sample();d.loc[0,field]='OTHER';self.assertTrue(run(d)['swing_label'].empty)
 def test_missing_schema(self):self.assertEqual(len(run(sample().drop(columns='extreme_price'))['quarantine']),8)
 def test_early_confirmation(self):
  d=sample();d.loc[0,'confirmed_at']=d.extreme_time.iloc[0];self.assertIn('INVALID_TIMESTAMP',set(run(d)['quarantine'].reason_code))
 def test_no_lookahead_replay(self):
  d=sample()
  for t in pd.date_range(d.extreme_time.iloc[0],d.confirmed_at.iloc[-1],freq='15min'):
   pd.testing.assert_frame_equal(labels(run(d,as_of=t)),labels(run(d[d.confirmed_at<=t],as_of=t)))
 def test_idempotence_values(self):pd.testing.assert_frame_equal(labels(run(sample())),labels(run(sample())))
 def test_rule_version(self):self.assertEqual(set(run(sample(),config=replace(Config(),rule_version='draft2'))['swing_label'].rule_version),{'draft2'})
 def test_ohlcv_gap(self):
  d=sample().iloc[:1].copy();d.extreme_time=pd.Timestamp('2026-01-05 11:15+07:00');d.confirmed_at=pd.Timestamp('2026-01-05 12:15+07:00')
  bars=pd.DataFrame(dict(Datetime=['2026-01-05 '+x for x in ['11:15','13:00','13:15','13:30']],Open=100,High=101,Low=99,Close=100,Volume=10))
  self.assertTrue(run(d,ohlcv=bars)['swing_label'].empty)
  d.confirmed_at=pd.Timestamp('2026-01-05 13:45+07:00');self.assertEqual(len(run(d,ohlcv=bars)['swing_label']),1)
 def test_no_mutation(self):
  d=sample();copy=d.copy(deep=True);run(d);pd.testing.assert_frame_equal(d,copy)
 def test_empty_schema(self):self.assertTrue(run(sample().iloc[:0])['swing_label'].empty)

if __name__=='__main__':unittest.main()

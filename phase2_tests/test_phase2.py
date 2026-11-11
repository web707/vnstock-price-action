import unittest
from dataclasses import replace
import pandas as pd
import numpy as np
from structure_builder_sfs.phase2 import LegConfig,build_legs,sensitivity,COLUMNS
from phase1_tests.test_phase1 import sample

END='2026-01-08 00:00+07:00'
def run(d=None,**kw):return build_legs(sample() if d is None else d,as_of=kw.pop('as_of',END),**kw)
def legs(d=None,**kw):return run(d,**kw)['swing_leg']

class Phase2Tests(unittest.TestCase):
 def test_geometry_and_start_atr(self):
  d=sample().iloc[:2].copy();d.atr_at_extreme=[2,100]
  x=legs(d).iloc[0]
  self.assertEqual((x.direction,x.absolute_amplitude,x.pct_amplitude,x.atr_reference,x.amplitude_atr),('DOWN',10,.1,2,5))
  self.assertEqual(x.available_at,d.confirmed_at.max())
 def test_up_geometry(self):
  x=legs().iloc[1];self.assertEqual(x.direction,'UP');self.assertEqual(x.absolute_amplitude,20);self.assertAlmostEqual(x.pct_amplitude,20/90)
 def test_TC07_small_amplitude(self):
  x=legs(config=LegConfig(atr_multiplier=100)).iloc[0]
  self.assertFalse(x.amplitude_filter_passed);self.assertEqual(x.reason_code,'AMPLITUDE_TOO_SMALL_INTERNAL');self.assertEqual(x.classification,'UNCLASSIFIED')
 def test_TC08_large_is_not_major(self):
  x=legs(sample().iloc[:2]);self.assertTrue(x.amplitude_filter_passed.all());self.assertEqual(set(x.classification),{'UNCLASSIFIED'});self.assertNotIn('status',x)
 def test_TC09_invalid_start_atr(self):
  for value in [None,np.nan,0,-1,np.inf]:
   with self.subTest(value=value):
    d=sample().iloc[:2].copy();d.loc[0,'atr_at_extreme']=value;x=legs(d).iloc[0]
    for col in ['atr_reference','amplitude_atr','amplitude_threshold','amplitude_filter_passed']:self.assertTrue(pd.isna(x[col]))
    self.assertEqual(x.reason_code,'ATR_MISSING_OR_INVALID')
 def test_missing_end_atr_not_used(self):
  d=sample().iloc[:2].copy();d.loc[1,'atr_at_extreme']=np.nan;self.assertEqual(legs(d).iloc[0].amplitude_atr,5)
 def test_exact_threshold(self):
  for amp,expected in [(6,True),(5.999,False),(6.001,True)]:
   d=sample().iloc[:2].copy();d.extreme_price=[100,100-amp];self.assertEqual(legs(d).iloc[0].amplitude_filter_passed,expected)
 def test_sensitivity_counts(self):
  d=sample().iloc[:2].copy();d.extreme_price=[100,95]
  r=sensitivity(legs(d));self.assertEqual(list(r.passed),[1,1,1,0]);self.assertEqual(list(r.legs),[1]*4)
 def test_sensitivity_missing(self):
  d=sample().iloc[:2].copy();d.atr_at_extreme=None;r=sensitivity(legs(d));self.assertTrue((r.missing_atr==1).all());self.assertTrue(r.pass_rate.isna().all())
 def test_empty_and_single(self):
  for n in [0,1]:self.assertEqual(list(legs(sample().iloc[:n]).columns),COLUMNS);self.assertEqual(len(legs(sample().iloc[:n])),0)
 def test_invalid_config(self):
  for k in [0,-1,float('inf'),float('nan'),True]:
   with self.assertRaises(ValueError):LegConfig(atr_multiplier=k)
  with self.assertRaises(ValueError):LegConfig(rule_version='')
 def test_no_mutation(self):
  d=sample();original=d.copy(deep=True);run(d);pd.testing.assert_frame_equal(d,original)
 def test_TC16_idempotent(self):pd.testing.assert_frame_equal(legs(),legs())
 def test_TC17_rule_namespaces(self):
  a=legs();b=legs(config=LegConfig(rule_version='test-other'));self.assertFalse(set(a.leg_id)&set(b.leg_id))
 def test_config_hash_changes(self):
  self.assertNotEqual(LegConfig().config_hash,LegConfig(atr_multiplier=2).config_hash)
 def test_input_order(self):pd.testing.assert_frame_equal(legs(),legs(sample().iloc[::-1]))
 def test_duplicate_no_extra_leg(self):
  d=sample();pd.testing.assert_frame_equal(legs(d),legs(pd.concat([d,d.iloc[[0]]])))
 def test_same_type_is_quarantined(self):
  d=sample().iloc[:2].copy();d.swing_type='HIGH';r=run(d);self.assertTrue(r['swing_leg'].empty);self.assertEqual(len(r['quarantine']),2)
 def test_same_time_is_quarantined(self):
  d=sample().iloc[:2].copy();d.extreme_time=d.extreme_time.iloc[0];d.confirmed_at=d.confirmed_at.iloc[0];self.assertTrue(legs(d).empty)
 def test_inverted_confirmations_price_order(self):
  d=sample().iloc[:2].copy();d.loc[0,'confirmed_at']=d.confirmed_at.iloc[1]+pd.Timedelta(hours=1)
  x=legs(d).iloc[0];self.assertEqual((x.start_swing_id,x.end_swing_id),('1','2'));self.assertEqual(x.available_at,d.confirmed_at.max())
 def test_TC15_replay_each_bar_and_prefix(self):
  d=sample();full=legs(d)
  for t in pd.date_range(d.extreme_time.min(),d.confirmed_at.max(),freq='15min'):
   got=legs(d,as_of=t)
   pd.testing.assert_frame_equal(got,legs(d[d.confirmed_at<=t],as_of=t))
   expected=full[full.available_at<=t].reset_index(drop=True)
   pd.testing.assert_frame_equal(got,expected,check_dtype=False)
 def test_future_bad_data_no_influence(self):
  d=sample();t=d.confirmed_at.iloc[2];x=d.iloc[[0]].copy();x.confirmed_at=d.confirmed_at.iloc[-1]+pd.Timedelta(days=1);x.extreme_price=-1
  pd.testing.assert_frame_equal(legs(d,as_of=t),legs(pd.concat([d,x]),as_of=t))
 def test_late_insert_does_not_erase_published_leg(self):
  d=sample().iloc[:3].copy();d.loc[1,'confirmed_at']=d.confirmed_at.iloc[-1]+pd.Timedelta(hours=2)
  # Original endpoints must alternate in the published sequence.
  d.loc[2,'swing_type']='LOW'
  before=legs(d,as_of=d.confirmed_at.iloc[2]);r=run(d)
  pd.testing.assert_frame_equal(before,r['swing_leg']);self.assertEqual(len(r['phase2_quarantine']),1)
  self.assertIn('DATA_ORDER_AMBIGUOUS',set(r['phase2_audit'].reason_code))
 def test_invalid_later_batch_preserves_history(self):
  d=sample().iloc[:3].copy();d.loc[2,'swing_type']='LOW'
  x=legs(d);self.assertEqual(len(x),1);self.assertEqual(x.iloc[0].end_swing_id,'2')
 def test_duration_no_calendar(self):
  x=legs().iloc[0];self.assertEqual(x.duration_minutes,120);self.assertTrue(pd.isna(x.duration_bars))
 def test_duration_contiguous_and_future_bars(self):
  d=sample().iloc[:2].copy();dates=pd.date_range(d.extreme_time.min(),d.confirmed_at.max(),freq='15min')
  o=pd.DataFrame(dict(Datetime=dates,Open=100,High=101,Low=99,Close=100,Volume=1))
  x=legs(d,ohlcv=o);self.assertEqual(x.iloc[0].duration_bars,8)
  future=o.iloc[[-1]].copy();future.Datetime+=pd.Timedelta(days=10)
  pd.testing.assert_frame_equal(x,legs(d,ohlcv=pd.concat([o,future])))
 def test_calendar_gap_not_inferred(self):
  d=sample().iloc[:2].copy();dates=pd.date_range(d.extreme_time.min(),d.confirmed_at.max(),freq='15min')
  o=pd.DataFrame(dict(Datetime=dates,Open=100,High=101,Low=99,Close=100,Volume=1)).drop(index=5)
  self.assertTrue(pd.isna(legs(d,ohlcv=o).iloc[0].duration_bars))
 def test_zero_amplitude(self):
  d=sample().iloc[:2].copy();d.extreme_price=100;x=legs(d).iloc[0];self.assertEqual(x.absolute_amplitude,0);self.assertFalse(x.amplitude_filter_passed)
 def test_json_null(self):
  d=sample().iloc[:2].copy();d.atr_at_extreme=None
  import json
  obj=json.loads(legs(d).to_json(orient='records'))[0];self.assertIsNone(obj['amplitude_atr']);self.assertIsNone(obj['amplitude_filter_passed'])

if __name__=='__main__':unittest.main()

import tempfile,unittest
import pandas as pd
from phase3_tests.test_phase3 import fixture,price,T
from structure_builder_sfs.phase5 import ResearchEngine,ResearchRules,rules_for,scenario_config,batch_oracle,canonical_rows
from structure_builder_sfs.phase5_metrics import describe
from structure_builder_sfs.phase3_store import StructureStore

def run(name,s=None,b=None):
 a,c=fixture();return ResearchEngine(s if s is not None else a,b if b is not None else c,rules_for(name)).advance(T('18:15'))
def first(r):return r['market_structure'].iloc[0]
class Phase5Tests(unittest.TestCase):
 def test_D05_current_formula(self):self.assertEqual(float(rules_for('BASELINE').tolerance({},dict(extreme_price=20000))),2.)
 def test_D05_point_one_percent(self):self.assertEqual(float(rules_for('D05_PCT_0_1').tolerance({},dict(extreme_price=20000))),20.)
 def test_tick_split_date_and_bands(self):
  p=rules_for('D05_TICK_PROXY');r=dict(ticker='FPT',extreme_time='2026-09-20',extreme_price=64000);self.assertAlmostEqual(p.effective_tick(r),100/1.1)
  r['extreme_time']='2026-09-21';self.assertEqual(p.effective_tick(r),100)
  for price_,tick in [(9990,10),(10000,50),(50000,100)]:r.update(ticker='HPG',extreme_price=price_);self.assertEqual(p.effective_tick(r),tick)
 def test_tick_pair_max_and_float_epsilon(self):
  p=rules_for('D05_TICK_PROXY');a=dict(ticker='FPT',extreme_time='2026-09-20',extreme_price=64000);b=dict(a,extreme_time='2026-09-21');self.assertAlmostEqual(float(p.tolerance(a,b)),100.01)
 def test_tick_missing_metadata_fail_closed(self):
  with self.assertRaisesRegex(ValueError,'TICK_METADATA_MISSING'):rules_for('D05_TICK_PROXY').effective_tick(dict(ticker='OTHER'))
 def test_D06_C_direction_symmetry(self):
  for down,level in [(False,100),(True,140)]:s,b=fixture(down);self.assertEqual(first(run('D06_C',s,b)).protected_level,level)
 def test_D06_C_missing_pivot_ATR(self):
  s,b=fixture();s.loc[2,'atr_at_extreme']=None;x=first(run('D06_C',s,b));self.assertEqual(x.status,'UNCLEAR');self.assertEqual(x.reason_code,'PROTECTED_PIVOT_ATR_MISSING')
 def test_D07_C_two_closes(self):
  s,b=fixture();e=ResearchEngine(s,price(b,'16:00',109),rules_for('D07_C'));self.assertEqual(first(e.advance(T('16:15'))).status,'CONFIRMED');self.assertEqual(first(e.advance(T('16:30'))).invalidated_at,T('16:30'))
 def test_D07_C_recovery_reset(self):
  s,b=fixture();b=price(price(price(b,'16:00',109),'16:15',120),'16:30',109);self.assertEqual(first(run('D07_C',s,b)).invalidated_at,T('17:00'))
 def test_D07_C_touch_reset(self):
  s,b=fixture();b=price(price(price(b,'16:00',109),'16:15',110),'16:30',109);self.assertEqual(first(run('D07_C',s,b)).invalidated_at,T('17:00'))
 def test_D07_C_invalid_bar_reset(self):
  s,b=fixture();b=price(b,'16:00',109);b.loc[b.Datetime==T('16:15'),'High']=0;self.assertEqual(first(run('D07_C',s,b)).invalidated_at,T('17:00'))
 def test_D07_C_birth_guard_unchanged(self):
  s,b=fixture();self.assertEqual(first(run('D07_C',s,price(b,'15:45',109))).reason_code,'PROTECTED_LEVEL_VIOLATED_AT_AVAILABILITY')
 def test_TC15_future_mutation_does_not_change_past(self):
  s,b=fixture()
  for n in ['BASELINE','D05_PCT_0_1','D06_C','D07_C','D04_2_5','D01_OVERLAP_DIAGNOSTIC']:
   a=ResearchEngine(s,b,rules_for(n)).advance(T('16:00'));z=ResearchEngine(s,price(b,'16:00',90),rules_for(n)).advance(T('16:00'));self.assertEqual(canonical_rows(a['market_structure_event']),canonical_rows(z['market_structure_event']))
 def test_TC16_repeat_and_store_idempotency(self):
  a=run('D07_C');b=run('D07_C');self.assertEqual(canonical_rows(a['market_structure']),canonical_rows(b['market_structure']))
  with tempfile.TemporaryDirectory() as tmp:
   st=StructureStore(tmp+'/db');st.save(a);st.save(b);self.assertEqual(st.db.execute('select count(*) from market_structure_event').fetchone()[0],len(a['market_structure_event']));st.close()
 def test_TC17_version_coexistence(self):
  a=run('BASELINE');b=run('D07_C');self.assertNotEqual(first(a).structure_id,first(b).structure_id)
  with tempfile.TemporaryDirectory() as tmp:
   st=StructureStore(tmp+'/db');st.save(a);st.save(b);self.assertEqual(st.db.execute('select count(*) from structure_rule_version').fetchone()[0],2);st.close()
 def test_TC17_same_version_different_config_rejected(self):
  a=run('BASELINE');c=rules_for('BASELINE').as_dict();c['experiment']['classification_atr']=2.5;s,b=fixture();z=ResearchEngine(s,b,ResearchRules(c)).advance(T('18:15'))
  with tempfile.TemporaryDirectory() as tmp:
   st=StructureStore(tmp+'/db');st.save(a)
   with self.assertRaisesRegex(ValueError,'RULE_VERSION_CONFIG_CONFLICT'):st.save(z)
   st.close()
 def test_lifetime_censoring_separate(self):
  s,b=fixture();p=rules_for('BASELINE');m,d=describe(run('BASELINE',s,price(b,'16:00',109)),b,p);self.assertEqual(m['completed_mean_hours'],.25);self.assertEqual(m['completed_median_bars'],1)
  m,d=describe(run('BASELINE'),b,p);self.assertIsNone(m['completed_mean_hours']);self.assertEqual(m['active_censored'],1)
 def test_D04_no_lifecycle_change(self):
  a=run('BASELINE');b=run('D04_2_5')
  for k in ['start_swing_id','end_swing_id','status','confirmed_at','invalidated_at','protected_level']:self.assertEqual(list(a['market_structure'][k]),list(b['market_structure'][k]))
 def test_OAT_single_semantic_change(self):
  e=scenario_config('BASELINE')['experiment']
  for n,key in [('D05_TICK_PROXY','tolerance'),('D05_PCT_0_1','tolerance'),('D06_C','buffer_atr'),('D07_C','consecutive_closes'),('D04_2_5','classification_atr'),('D01_OVERLAP_DIAGNOSTIC','overlap')]:
   z=scenario_config(n)['experiment'];self.assertEqual({k for k in e if e[k]!=z[k]},{'name',key})
 def test_oracle_broken_and_prebroken(self):
  s,b=fixture()
  for n in ['BASELINE','D06_C','D07_C']:
   for at in ['16:00','15:45']:
    bars=price(b,at,99);self.assertEqual(first(run(n,s,bars)).status,batch_oracle(s,bars,T('18:15'),rules_for(n))[0]['status'])
 def test_inputs_unchanged(self):
  s,b=fixture();a=s.copy(deep=True);z=b.copy(deep=True);run('D06_C',s,b);pd.testing.assert_frame_equal(s,a);pd.testing.assert_frame_equal(b,z)

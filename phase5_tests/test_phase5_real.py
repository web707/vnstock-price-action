import tempfile,unittest
from pathlib import Path
import pandas as pd
from structure_builder_sfs.phase5 import ResearchEngine,rules_for,SCENARIOS,batch_oracle,canonical_rows
from structure_builder_sfs.phase3_store import StructureStore
ROOT=Path(__file__).resolve().parents[1];END='2026-10-28 23:59:59+07:00'
class RealValidationTests(unittest.TestCase):
 def check_ticker(self,t):
  s=pd.read_csv(ROOT/f'reports/layer1_schema/{t}.csv');b=pd.read_csv(ROOT/f'reports/layer1/{t}_clean.csv');closes=pd.to_datetime(b.Datetime)+pd.Timedelta(minutes=15);known=pd.to_datetime(s.confirmed_at).dt.tz_localize('Asia/Ho_Chi_Minh')
  with tempfile.TemporaryDirectory() as tmp:
   st=StructureStore(tmp+'/db')
   for n in SCENARIOS:
    p=rules_for(n);batch=ResearchEngine(s,b,p);final=batch.advance(END);inc=ResearchEngine(s,b,p)
    for at in closes:
     inc.advance(at);self.assertEqual(inc.events,[e for e in batch.events if e['available_at']<=at],f'{t} {n} {at}')
    self.assertEqual(canonical_rows(inc.advance(END)['market_structure']),canonical_rows(final['market_structure']))
    for fraction in [.25,.5,.75]:
     at=closes.iloc[int(len(closes)*fraction)];prefix=ResearchEngine(s[known<=at],b[closes<=at],p).advance(at);expected=batch.snapshot(at)
     for tab in ['market_structure','market_structure_event']:self.assertEqual(canonical_rows(prefix[tab]),canonical_rows(expected[tab]))
    oracle=pd.DataFrame(batch_oracle(s,b,END,p));actual=final['market_structure'];actual=actual[actual.geometry_qualified][oracle.columns]
    self.assertEqual(canonical_rows(actual.sort_values(['start_swing_id','end_swing_id']).reset_index(drop=True)),canonical_rows(oracle.sort_values(['start_swing_id','end_swing_id']).reset_index(drop=True)))
    if n=='BASELINE':
     old=pd.read_csv(ROOT/f'reports/layer2_phase3/{t}/market_structure.csv');fields=['start_swing_id','end_swing_id','status','structure_direction','protected_level'];old[fields[:2]]=old[fields[:2]].astype(str);self.assertEqual(canonical_rows(final['market_structure'][fields]),canonical_rows(old[fields]))
    st.save(final);count=st.db.execute('select count(*) from market_structure_event').fetchone()[0];st.save(final);self.assertEqual(count,st.db.execute('select count(*) from market_structure_event').fetchone()[0])
    print(f'TC15/TC16/TC17 {t} {n}: {len(closes)} candle cutoffs + 3 fresh input-prefix reruns + independent batch oracle + repeated SQLite save PASS',flush=True)
   self.assertEqual(st.db.execute('select count(*) from structure_rule_version').fetchone()[0],len(SCENARIOS));st.close()
 def test_TC15_TC16_TC17_HPG(self):self.check_ticker('HPG')
 def test_TC15_TC16_TC17_FPT(self):self.check_ticker('FPT')
 def test_TC15_TC16_TC17_VNM(self):self.check_ticker('VNM')
 def test_TC15_TC16_TC17_VCB(self):self.check_ticker('VCB')
 def test_TC15_TC16_TC17_SSI(self):self.check_ticker('SSI')

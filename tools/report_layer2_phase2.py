"""Reproducible Phase 2 comparison using preserved Phase 1 input snapshots."""
import sys,json,hashlib
from pathlib import Path
from dataclasses import asdict
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from structure_builder_sfs.phase2 import build_legs,sensitivity
from structure_builder import MarketStructureBuilder

OUT=ROOT/'reports/layer2_phase2'
ASOF='2026-10-28 23:59:59+07:00'

def main():
 OUT.mkdir(exist_ok=True)
 summary=[]; units=[]; legacy=[]; regime=[]; manifest=[]
 for s in ['HPG','FPT','VNM','VCB','SSI']:
  sp=ROOT/f'reports/layer1_schema/{s}.csv';op=ROOT/f'reports/layer1/{s}_clean.csv'
  d=pd.read_csv(sp);o=pd.read_csv(op);r=build_legs(d,o,as_of=ASOF);x=r['swing_leg']
  for k in ['swing_leg','swing_label','audit','quarantine','phase2_audit','phase2_quarantine']:
   r[k].to_csv(OUT/f'{s}_{k}.csv',index=False)
  (OUT/f'{s}_batch_log.json').write_text(json.dumps(r['batch_log'],indent=2),encoding='utf-8')
  (OUT/'rule_config.json').write_text(json.dumps(r['leg_config'],indent=2),encoding='utf-8')
  sen=sensitivity(x);sen.insert(0,'ticker',s);summary.append(sen)
  p=d.extreme_price;tol=(p*.0001).clip(lower=1)
  ticks=p.map(lambda p:10 if p<10000 else 50 if p<50000 else 100)
  units.append(dict(ticker=s,unit='VND (observed scale; raw Yahoo snapshot)',price_min=p.min(),price_max=p.max(),
   tolerance_min=tol.min(),tolerance_max=tol.max(),reference_tick_min=ticks.min(),reference_tick_max=ticks.max(),
   swings_below_reference_tick=int((tol<ticks).sum()),swings=len(d),swings_off_nominal_tick=int(((p%ticks).abs()>1e-6).sum()),tick_source_status='SSI_CURRENT_PAGE_RETRIEVED_2026-10-30'))
  ls,st=MarketStructureBuilder(bear_after_up_is_unclear=True).build_from_file(sp,as_of_time=ASOF)
  pd.DataFrame([asdict(z) for z in st]).to_csv(OUT/f'{s}_legacy_structures.csv',index=False)
  legacy.append(dict(ticker=s,input_swings=len(d),legs=len(x),legacy_structures=len(st),new_structures='NOT_IMPLEMENTED_PHASE2',
   quarantine=len(r['quarantine']),phase2_quarantine=len(r['phase2_quarantine']),
   passed_3atr=int(x.amplitude_filter_passed.fillna(False).sum()),missing_atr=int(x.atr_reference.isna().sum())))
  # Reuse existing Layer 1 regime annotations as descriptive, ex-post strata ONLY.
  bytime={pd.Timestamp(t):g for t,g in zip(o.Datetime,o.regime)}
  groups=x.end_time.map(lambda t:bytime.get(t,'UNCLASSIFIED'))
  for g,sub in x.groupby(groups):
   tab=sensitivity(sub);tab.insert(0,'ticker',s);tab.insert(1,'regime_at_end_ex_post',g);regime.append(tab)
  for path in [sp,op]:manifest.append(dict(path=str(path.relative_to(ROOT)),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
  print(f'{s}: swings={len(d)} legs={len(x)} quarantine={len(r["quarantine"])} phase2_quarantine={len(r["phase2_quarantine"])}; sensitivity passed={list(sen.passed)}',flush=True)
 pd.concat(summary,ignore_index=True).to_csv(OUT/'sensitivity.csv',index=False)
 pd.concat(regime,ignore_index=True).to_csv(OUT/'sensitivity_by_regime.csv',index=False)
 pd.DataFrame(units).to_csv(OUT/'D05_price_units_tolerance.csv',index=False)
 pd.DataFrame(legacy).to_csv(OUT/'legacy_comparison.csv',index=False)
 (OUT/'input_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
 print('REPORT_COMPLETED; no structure classification or trading evaluation performed.',flush=True)
if __name__=='__main__':main()

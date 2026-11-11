import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
from structure_builder_sfs.phase5 import ResearchEngine,rules_for,SCENARIOS,batch_oracle
from structure_builder_sfs.phase5_metrics import describe
from structure_builder_sfs.phase3_store import StructureStore
OUT=ROOT/'reports/layer2_phase5';END='2026-10-28 23:59:59+07:00'
st=StructureStore(OUT/'research_events.sqlite');summaries=[];lifetimes=[];boundaries=[];labels=[];timing=[]
for t in ['HPG','FPT','VNM','VCB','SSI']:
 s=pd.read_csv(ROOT/f'reports/layer1_schema/{t}.csv');b=pd.read_csv(ROOT/f'reports/layer1/{t}_clean.csv');base=None;basekeys=None;baseframe=None
 for name in SCENARIOS:
  p=rules_for(name);r=ResearchEngine(s,b,p).advance(END);m,life=describe(r,b,p);rows=r['market_structure'];q=rows[rows.geometry_qualified];keys={(x.start_swing_id,x.end_swing_id,x.structure_direction) for x in q.itertuples()}
  if base is None:base=m.copy();basekeys=keys;baseframe=rows.copy(deep=True)
  for k in ['candidate_windows','history_records','ever_confirmed','BROKEN','MAJOR','INTERNAL']:m['delta_'+k]=m[k]-base[k]
  m['delta_broken_rate_pp']=m['broken_rate_pct']-base['broken_rate_pct'];m.update(boundary_retained=len(keys&basekeys),boundary_added=len(keys-basekeys),boundary_removed=len(basekeys-keys),boundary_jaccard=len(keys&basekeys)/len(keys|basekeys))
  for change,pairs in [('ADDED',keys-basekeys),('REMOVED',basekeys-keys)]:
   for a,z,d in sorted(pairs):boundaries.append(dict(ticker=t,scenario=name,change=change,start=a,end=z,direction=d))
  if name in ['BASELINE','D05_TICK_PROXY','D05_PCT_0_1']:
   prior={}
   for sw in s.to_dict('records'):
    kind=sw['swing_type'];ref=prior.get(kind)
    if ref:
     diff=sw['extreme_price']-ref['extreme_price'];tol=float(p.tolerance(ref,sw));lab=('EQH' if kind=='HIGH' else 'EQL') if abs(diff)<=tol else ('HH' if kind=='HIGH' else 'HL') if diff>0 else ('LH' if kind=='HIGH' else 'LL')
     labels.append(dict(ticker=t,scenario=name,swing_id=sw['swing_id'],reference_swing_id=ref['swing_id'],label=lab,tolerance=tol,difference=diff))
    prior[kind]=sw
  if name in ['D06_C','D07_C']:
   joined=baseframe[baseframe.confirmed_at.notna()].merge(rows[rows.confirmed_at.notna()],on=['start_swing_id','end_swing_id','structure_direction'],suffixes=('_base','_variant'))
   for _,x in joined.iterrows():
    old=pd.to_datetime(x.invalidated_at_base);new=pd.to_datetime(x.invalidated_at_variant)
    reason='STILL_ACTIVE_BOTH' if pd.isna(old) and pd.isna(new) else 'BROKEN_BASE_ACTIVE_VARIANT' if pd.notna(old) and pd.isna(new) else 'NEW_BREAK' if pd.isna(old) else 'DELAYED' if new>old else 'SAME_TIME' if new==old else 'EARLIER'
    timing.append(dict(ticker=t,scenario=name,start=x.start_swing_id,end=x.end_swing_id,change=reason,delay_hours=(new-old).total_seconds()/3600 if pd.notna(old) and pd.notna(new) else None))
  dest=OUT/t/name;dest.mkdir(parents=True,exist_ok=True)
  for tab in ['market_structure','market_structure_event','audit']:r[tab].to_csv(dest/(tab+'.csv'),index=False)
  (dest/'rule_config.json').write_text(json.dumps(p.as_dict(),ensure_ascii=False,indent=2)+'\n')
  pd.DataFrame(batch_oracle(s,b,END,p)).to_csv(dest/'independent_batch_oracle.csv',index=False)
  st.save(r);st.save(r);summaries.append(m);lifetimes.append(life)
  print(t,name,{k:m[k] for k in ['candidate_windows','history_records','ever_confirmed','BROKEN','MAJOR','INTERNAL']},flush=True)
st.close();pd.DataFrame(summaries).to_csv(OUT/'sensitivity_summary.csv',index=False)
life=pd.concat(lifetimes,ignore_index=True);life.to_csv(OUT/'structure_lifetimes.csv',index=False)
pd.DataFrame(boundaries).to_csv(OUT/'boundary_changes.csv',index=False);pd.DataFrame(labels).to_csv(OUT/'D05_label_comparisons.csv',index=False);pd.DataFrame(timing).to_csv(OUT/'break_timing_changes.csv',index=False)
cohort=life.groupby(['ticker','scenario','cohort']).agg(ever_confirmed=('structure_id','size'),BROKEN=('censored',lambda x:int((~x).sum())),median_observed_age_hours=('observed_age_hours','median')).reset_index();cohort['broken_rate_pct']=100*cohort.BROKEN/cohort.ever_confirmed;cohort.to_csv(OUT/'monthly_cohorts.csv',index=False)

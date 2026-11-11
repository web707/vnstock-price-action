"""Phase5 validation only; never modify Layer1/Layer2 or approved V1 config."""
from __future__ import annotations
import collections,csv,hashlib,json,platform,sys,time,unittest,copy
from pathlib import Path
from datetime import datetime,timezone
from decimal import Decimal
from reversal_setup_detector.phase4_config import ApprovedRules
from reversal_setup_detector.calendar_phase3 import empirical_calendar
from reversal_setup_detector.context import ContextProvider
from reversal_setup_detector.lifecycle import scan_lifecycle
from reversal_setup_detector.persistence import connect,persist_batch,export_long_setups,statistics as db_statistics,canonical_json
from reversal_setup_detector.tools.report_phase1 import load_rows,write_csv
from reversal_setup_detector.tools.report_phase2 import events,SOURCE
from reversal_setup_detector.tools.report_phase4 import slot_audit,table_hash
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'reports/layer3_phase5'
TICKERS=('HPG','FPT','VNM','VCB','SSI')
def write(name,value):
 (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
def stamp():return datetime.now(timezone.utc).isoformat()
def abbreviated(z):
 return dict(candidates=[{k:s[k] for k in ('setup_id','status','reason_code','available_at','found_at','resolved_at','reversal_candle_time','body_ratio','context_structure_ids','context_age_bars','window_crosses_session','bars_checked')} for s in z['candidates']],events=[{k:e[k] for k in ('event_id','setup_id','event_type','available_at','reason_code')} for e in z['events']])
def run():
 OUT.mkdir(parents=True,exist_ok=True)
 rules=ApprovedRules()
 print('PHASE5_REAL_RUN_START',stamp(),'python',sys.version.split()[0],platform.platform(),flush=True)
 print('DECISIONS', 'D01 APPROVED D02 APPROVED D03 CONDITIONALLY_APPROVED D04 APPROVED true D05 APPROVED',flush=True)
 full=[]; audits=[]; funnel=[]; traces=[]; points=[]
 audit=slot_audit();write('INTRADAY_VOLUME_AUDIT.json',audit);write_csv(OUT/'VOLUME_BY_TICKER_SLOT.csv',audit['rows'])
 for ticker in TICKERS:
  print('BEGIN_TICKER',ticker,stamp(),flush=True)
  rows=load_rows(ticker);cal=empirical_calendar(rules,ticker);provider=ContextProvider(events(ticker),rules=rules)
  params=dict(ticker=ticker,timeframe='15m',source_version=SOURCE)
  batch=scan_lifecycle(rows,rules,cal,provider,as_of=cal.end,**params)
  full.append(batch)
  by_batch={x['setup_id']:x for x in batch['candidates']}
  totals=collections.Counter();prev={};changes=[];t0=time.monotonic()
  # Compare a per-bar fresh prefix scan against a complete batch input limited only by as_of.
  # This is an exhaustive 1-to-1 prefix-vs-batch PIT check, not a sampled replay.
  for ix,row in enumerate(rows):
   when=row['available_at']
   serial=scan_lifecycle(rows[:ix+1],rules,cal,provider,as_of=when,**params)
   # Batch event journal projected to this as-of is the independent reference.
   expected_events=[{k:e[k] for k in ('event_id','setup_id','event_type','available_at','reason_code')} for e in batch['events'] if rules.timestamp(e['available_at'])<=rules.timestamp(when)]
   actual_events=abbreviated(serial)['events']
   if actual_events!=expected_events:
    raise AssertionError(f'PIT_EVENT_DIFFERENCE {ticker} bar={ix} available_at={when}')
   from_events={e['setup_id']:e['event_type'] for e in expected_events}
   projected={sid:('WAITING_REVERSAL' if status=='CREATED' else 'FOUND' if status=='REVERSAL_FOUND' else status) for sid,status in from_events.items()}
   if {x['setup_id']:x['status'] for x in serial['candidates']}!=projected:
    raise AssertionError(f'PIT_STATE_DIFFERENCE {ticker} bar={ix} available_at={when}')
   now={s['setup_id']:s['status'] for s in serial['candidates']}
   for sid,status in now.items():
    if prev.get(sid)!=status:changes.append(dict(available_at=when,setup_id=sid,from_status=prev.get(sid),to_status=status))
   prev=now
   totals['bars_checked']+=1
  points.append(dict(ticker=ticker,bars_checked=totals['bars_checked'],prefix_batch_equal=True,full_batch_candidates=len(batch['candidates']),elapsed_seconds=round(time.monotonic()-t0,3),changes=changes))
  print('PIT_PASS',ticker,'bars',totals['bars_checked'],'elapsed',points[-1]['elapsed_seconds'],'candidates',len(batch['candidates']),flush=True)
  # More than just an existing future bar: append a future fake candle and future structure events,
  # then assert the original historical checkpoint is unchanged.
  checkpoints=sorted(set([rows[max(0,len(rows)//2)]['available_at'],rows[-1]['available_at']]+[x['available_at'] for x in batch['events']]))
  base_events=events(ticker)
  for at in checkpoints:
   original=scan_lifecycle(rows,rules,cal,provider,as_of=at,**params)
   future_idx=next((j for j,v in enumerate(rows) if v['available_at']>at),None)
   if future_idx is not None:
    altered=copy.deepcopy(rows)
    altered[future_idx]['close']=str(Decimal(altered[future_idx]['close'])*Decimal('1.37'))
    altered[future_idx]['high']=str(max(Decimal(altered[future_idx]['high']),Decimal(altered[future_idx]['close'])))
    later=scan_lifecycle(altered,rules,cal,provider,as_of=at,**params)
    assert abbreviated(original)==abbreviated(later),(ticker,at,'FUTURE_CANDLE_CHANGED_PAST')
   # Introduce a late availability event by cloning an actual event, with unique future ID.
   # Future events must be discarded before their payload/state can enter context projection.
   import pandas as pd
   fake=base_events.iloc[-1:].copy()
   fake['available_at']='2030-01-02T10:00:00+07:00'
   if 'event_id' in fake.columns:fake['event_id']='synthetic_future_event_'+ticker
   augmented=pd.concat([base_events,fake],ignore_index=True)
   augmented_provider=ContextProvider(augmented,rules=rules)
   later=scan_lifecycle(rows,rules,cal,augmented_provider,as_of=at,**params)
   assert abbreviated(original)==abbreviated(later),(ticker,at,'FUTURE_STRUCTURE_CHANGED_PAST')
  print('FUTURE_APPEND_PASS',ticker,'checkpoints',len(checkpoints),flush=True)
  m=batch['metrics']
  funnel.append(dict(ticker=ticker,candles=m['total_candles_processed'],valid_red_triplets=m['valid_red_triplets'],triplets_with_context=m['candidates_created'],candidates=m['candidates_created'],FOUND=m['found'],EXPIRED=m['expired'],INVALIDATED=m['invalidated'],WAITING=m['waiting']))
  print('BEGIN_TRACES',ticker,stamp(),flush=True)
  for s in batch['candidates']:
   if s['status']=='FOUND':
    raw_by_time={rules.timestamp(x['candle_time']).isoformat():x for x in rows}
    four=[]
    for label,at in zip(('R1','R2','R3','G'),[*s['red_candle_times'],s['reversal_candle_time']]):
     raw=raw_by_time[at]
     assert raw['available_at']<=s['found_at']
     four.append(dict(label=label,**raw))
    assert s['context_structure_ids'] and len(s['context_structure_ids'])==2
    snap=provider.snapshot(s['setup_detected_at'],ticker=ticker,timeframe='15m',source_version=SOURCE)
    structure_index={x['structure_id']:x for x in snap['major_sequence']}
    pair=[]
    for sid in s['context_structure_ids']:
     assert sid in structure_index
     obj=structure_index[sid]
     assert obj['status']=='CONFIRMED' and obj['structure_direction']=='DOWN'
     pair.append(obj)
    print('TRACE_OK',ticker,s['setup_id'],stamp(),flush=True)
    traces.append(dict(ticker=ticker,setup_id=s['setup_id'],found_at=s['found_at'],rule_version=s['rule_version'],structure_ids=s['context_structure_ids'],structures_at_R3=pair,candles=four,body_ratio=s['body_ratio'],window_crosses_session=s['window_crosses_session'],context_age_bars=s['context_age_bars'],calendar_source='UNVERIFIED'))
 print('FUNNEL',canonical_json(funnel),flush=True)
 db=OUT/'reversal_setup_phase5_validation.sqlite'
 if db.exists():db.unlink()
 conn=connect(db)
 try:
  passes=[]
  for n in (1,2):
   result=persist_batch(conn,full)
   p={k:v for k,v in result.items() if k!='actions'}
   p.update(pass_no=n,table_sha256=table_hash(conn),db=db_statistics(conn))
   passes.append(p);print('PERSISTENCE_PASS',canonical_json(p),flush=True)
  assert passes[0]['table_sha256']==passes[1]['table_sha256']
  assert passes[0]['inserted']==4 and passes[0]['events_inserted']==8
  assert passes[1]['inserted']==passes[1]['updated']==passes[1]['events_inserted']==0
  assert passes[1]['duplicates_prevented']==4 and passes[1]['events_duplicates']==8
  signals=export_long_setups(conn)
  assert len(signals)==len(traces)==2
  assert {x['setup_id'] for x in signals}=={x['setup_id'] for x in traces}
  (OUT/'LONG_SETUP_VALIDATED.jsonl').write_text(''.join(canonical_json(x)+'\n' for x in signals),encoding='utf-8')
 finally:conn.close()
 write('PIT_REPLAY.json',points);write('FINAL_FUNNEL.json',funnel);write_csv(OUT/'FINAL_FUNNEL.csv',funnel)
 write('LONG_SETUP_TRACE.json',traces);write('SQL_TWO_PASS_PROOF.json',passes)
 # Sensitivity: strict lower bound >1, with same two candidates, leaving approved config unchanged.
 strict=[]
 for z in full:
  for s in z['candidates']:
   if s['status']=='FOUND':
    strict.append(dict(ticker=s['ticker'],setup_id=s['setup_id'],r3=s['red_candle_times'][2],ratio=s['body_ratio'],baseline='FOUND',strict_minimum_equality_would_fail=Decimal(s['body_ratio'])==Decimal('1'),note='Illustrative immediate G gate only; full lifecycle would require rerunning with a separately versioned rule'))
 write('STRICT_LOWER_BOUND_SENSITIVITY.json',strict)
 # Re-run all original tests and collect actual AT names from unittest IDs.
 suite=unittest.defaultTestLoader.discover(str(ROOT/'reversal_setup_detector/tests'),pattern='test_phase*.py',top_level_dir=str(ROOT))
 class Result(unittest.TextTestResult):
  def startTest(self,test):
   super().startTest(test)
   print('TEST',test.id(),flush=True)
 result=unittest.TextTestRunner(stream=sys.stdout,verbosity=1,resultclass=Result).run(suite)
 if not result.wasSuccessful():raise AssertionError('REGRESSION_SUITE_FAILED')
 tests=[]
 def walk(s):
  for x in s:
   if isinstance(x,unittest.TestSuite):yield from walk(x)
   else:yield x
 for test in walk(unittest.defaultTestLoader.discover(str(ROOT/'reversal_setup_detector/tests'),pattern='test_phase*.py',top_level_dir=str(ROOT))):
  import re
  m=re.search(r'test_(AT\d\d)(?:_|$)',test.id())
  if m:tests.append(dict(AT=m.group(1),test=test.id(),source='SYNTHETIC',status='PASS'))
 by={x['AT']:x for x in tests}
 for n in range(1,23):
  key=f'AT{n:02d}'
  if key not in by:raise AssertionError('MISSING_ACCEPTANCE_'+key)
 matrix=[by[f'AT{n:02d}'] for n in range(1,23)]
 write_csv(OUT/'AT01_AT22_MATRIX.csv',matrix);write('AT01_AT22_MATRIX.json',matrix)
 print('AT_MATRIX_PASS',len(matrix),'FULL_SUITE',result.testsRun,flush=True)
 print('PHASE5_REAL_RUN_END',stamp(),flush=True)
 return dict(pit=points,funnel=funnel,passes=passes,traces=traces,strict=strict,tests=result.testsRun,matrix=matrix,volume=audit)
if __name__=='__main__':run()

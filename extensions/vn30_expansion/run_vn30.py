"""Read-only Layer1 -> Layer2 -> Layer3 research runner; missing tickers explicit."""
import sys,csv,json,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import pandas as pd
from swing_detector import SwingDetectorConfig,detect_result
from swing_detector.io import export_result
from structure_builder_sfs.phase3 import build_structures
from reversal_setup_detector.phase4_config import ApprovedRules
from reversal_setup_detector.context import ContextProvider
from reversal_setup_detector.calendar_phase3 import empirical_calendar
from reversal_setup_detector.lifecycle import scan_lifecycle
from reversal_setup_detector.tools.report_phase1 import load_rows
from reversal_setup_detector.tools.report_phase2 import SOURCE
OUT=ROOT/'reports/extensions/vn30'
UNIVERSE_CONFIG = ROOT / 'extensions/daily_15m_collector/config.vn30.2026-07.json'

def run():
 OUT.mkdir(parents=True,exist_ok=True)
 universe=json.loads(UNIVERSE_CONFIG.read_text(encoding="utf-8"))
 tickers=universe["tickers"]
 rules=ApprovedRules()
 totals=dict(candles=0,red_triplets=0,with_context=0,candidates=0,FOUND=0,EXPIRED=0,INVALIDATED=0)
 rows=[]
 for ticker in tickers:
  file=ROOT/f'reports/layer1/{ticker}_clean.csv'
  record=dict(ticker=ticker,status='MISSING_15M_OHLCV',candles=0,red_triplets=0,with_context=0,candidates=0,FOUND=0,EXPIRED=0,INVALIDATED=0,detail='No 15m file in baseline; never use daily candles as substitute')
  if file.is_file():
   try:
    bars=pd.read_csv(file)
    # Re-run L1 in memory; export only to extension output.
    l1=detect_result(bars,SwingDetectorConfig(ticker=ticker))
    swingpath=OUT/f'{ticker}_layer1_recomputed.csv'
    export_result(l1,swingpath)
    swings=pd.read_csv(swingpath)
    # Re-run L2 with original baseline implementation/config, no writes to its SQLite.
    l2=build_structures(swings,bars,as_of='2026-10-28 23:59:59+07:00')
    e=l2['market_structure_event'];e.to_csv(OUT/f'{ticker}_layer2_events_recomputed.csv',index=False)
    candles=load_rows(ticker);calendar=empirical_calendar(rules,ticker)
    l3=scan_lifecycle(candles,rules,calendar,ContextProvider(e,rules=rules),as_of=calendar.end,ticker=ticker,timeframe='15m',source_version=SOURCE)
    m=l3['metrics']
    record.update(status='PROCESSED',candles=m['total_candles_processed'],red_triplets=m['valid_red_triplets'],with_context=m['candidates_created'],candidates=m['candidates_created'],FOUND=m['found'],EXPIRED=m['expired'],INVALIDATED=m['invalidated'],detail=f"L1_SWINGS={len(swings)} L2_EVENTS={len(e)}; L3 candidate context gate matches red-triplet context")
    (OUT/f'{ticker}_layer3_result.json').write_text(json.dumps(l3,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    for k in totals:totals[k]+=record[k]
   except Exception as exc:
    record.update(status='PIPELINE_ERROR',detail=repr(exc))
    (OUT/f'{ticker}_error.txt').write_text(traceback.format_exc(),encoding='utf-8')
  rows.append(record)
  print(json.dumps(record,ensure_ascii=False),flush=True)
 with (OUT/'VN30_FUNNEL.csv').open('w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 summary=dict(universe=tickers,universe_count=len(tickers),universe_provenance=universe["provenance"],processed=sum(x['status']=='PROCESSED' for x in rows),missing=[x['ticker'] for x in rows if x['status']=='MISSING_15M_OHLCV'],errors=[x['ticker'] for x in rows if x['status']=='PIPELINE_ERROR'],totals=totals,source='Local OHLCV snapshot; one HOSE VN30 constituent review, not historical membership',rules_version=rules.version,calendar_source_verified=False)
 (OUT/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print('SUMMARY',json.dumps(summary,ensure_ascii=False),flush=True)
 return 0 if not summary['errors'] else 2
if __name__=='__main__':sys.exit(run())

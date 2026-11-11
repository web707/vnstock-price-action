import sys,json,hashlib,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
from structure_builder_sfs.phase3 import build_structures
from structure_builder_sfs.phase3_store import StructureStore
out=ROOT/'reports/layer2_phase3';out.mkdir(parents=True,exist_ok=True)
store=StructureStore(out/'structure_events.sqlite');summary=[]
for ticker in ('HPG','FPT','VNM','VCB','SSI'):
    s=pd.read_csv(ROOT/f'reports/layer1_schema/{ticker}.csv');b=pd.read_csv(ROOT/f'reports/layer1/{ticker}_clean.csv')
    result=build_structures(s,b,as_of='2026-10-28 23:59:59+07:00')
    folder=out/ticker;folder.mkdir(exist_ok=True)
    for name in ('market_structure','market_structure_event','audit'):result[name].to_csv(folder/(name+'.csv'),index=False)
    for name in ('batch_log','rule_config'):(folder/(name+'.json')).write_text(json.dumps(result[name],indent=2,default=str)+'\n')
    store.save(result);store.save(result)
    summary.append(dict(ticker=ticker,input_swings=len(s),ohlcv_bars=len(b),**result['batch_log']))
store.close();pd.DataFrame(summary).to_csv(out/'summary.csv',index=False)
print(pd.DataFrame(summary).drop(columns=['rule_version','config_hash','as_of']).to_string(index=False))

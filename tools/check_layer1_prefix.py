"""Actual-stock prefix checks at each base confirmation and neighbouring cutoffs."""
import sys,json,logging
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from swing_detector import detect_result,clean_data
from compare_layer1 import old_frame,AS_OF
logging.basicConfig(level=logging.ERROR)
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/layer1'
results=[]
for symbol in ['HPG','FPT','VNM','VCB','SSI']:
    path=OUT/'fetched'/f'{symbol}.csv'
    if not path.exists():continue
    d,_=clean_data(pd.read_csv(path),as_of=AS_OF);new=detect_result(d);old=old_frame(d,2,3)
    cuts=set(range(14,len(d)+1,90))|{len(d)}
    for i,t in new.indices:cuts.update([t,t+1,min(t+2,len(d))])
    for t in old.confirm_index:cuts.update([int(t),int(t)+1])
    for n in sorted(cuts):
        cutoff=d.available_time.iloc[n-1]
        a=detect_result(d.iloc[:n]).swings;b=new.swings[new.swings.confirmed_at<=cutoff].reset_index(drop=True)
        pd.testing.assert_frame_equal(a,b,check_dtype=False)
        a=old_frame(d.iloc[:n],2,3);b=old[old.confirm_time<=cutoff].reset_index(drop=True)
        if len(a) or len(b):pd.testing.assert_frame_equal(a,b,check_dtype=False)
    results.append({'symbol':symbol,'prefixes_each_detector':len(cuts),'passed':True});print(results[-1],flush=True)
(OUT/'prefix_real.json').write_text(json.dumps(results,indent=2),encoding='utf-8')

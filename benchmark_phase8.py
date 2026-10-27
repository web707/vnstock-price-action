"""Run sequentially, no concurrent workloads. Cache in temporary directory."""
import argparse,time,json,tempfile
from pathlib import Path
from src.phase7.service import dashboard
from src.phase7.data import snapshot
from src.phase7.features import features
from src.phase8.fast import scan
import numpy as np

def run(path):
    t=time.perf_counter();old=dashboard(path);before=time.perf_counter()-t
    with tempfile.TemporaryDirectory() as d:
        new=scan(path,str(Path(d)/'cache.db'));disk=scan(path,str(Path(d)/'cache.db'))
    mismatches=[];errors={k:0. for k in ['ma50','ma200','rsi','adx','atr']};mapping={'rsi':'rsi14','atr':'atr14'}
    for r in new['items']:
        f=snapshot(path)['frames'][r['symbol']];i=features(f).iloc[-1]
        for k in errors:
            if r.get(k) is not None and np.isfinite(i[mapping.get(k,k)]):errors[k]=max(errors[k],abs(r[k]-float(i[mapping.get(k,k)])))
        if r.get('score') is not None and np.isfinite(i.adaptive_score) and abs(r['score']-i.adaptive_score)>1e-6:mismatches.append({'symbol':r['symbol'],'phase7':float(i.adaptive_score),'phase8':r['score'],'ad_flow':r.get('ad_flow'),'phase7_ad_flow':float(i.ad_flow)})
    return {'symbols':new['count'],'phase7_seconds':before,'phase8_cold_application_cache_seconds':new['seconds'],'phase8_disk_cache_seconds':disk['seconds'],'phase8_computed':new['computed'],'max_indicator_error':errors,'score_differences':mismatches,'limitations':['OS file cache not flushed; startup/migration/network not included.','Disk cached scan still reads and hashes histories; memory cache is faster.','Snapshot dataset in this ZIP only, not guaranteed on all PCs.']}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',default='data/state/qta_phase3_test.db');p.add_argument('--output',default='phase8_benchmark.json');a=p.parse_args();r=run(a.db);Path(a.output).write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2))

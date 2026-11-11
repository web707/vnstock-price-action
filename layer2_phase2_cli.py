"""Run Phase 2 and preserve outputs in a new snapshot directory."""
import argparse,json
from pathlib import Path
import pandas as pd
from structure_builder_sfs.phase2 import LegConfig,build_legs,sensitivity

def main():
    p=argparse.ArgumentParser()
    for name in ['swings','as-of','output']:p.add_argument('--'+name,required=True)
    p.add_argument('--ohlcv');p.add_argument('--atr-multiplier',type=float,default=3.)
    p.add_argument('--rule-version',default='sfs-layer2-phase2-DRAFT-001')
    a=p.parse_args();out=Path(a.output)
    if out.exists():p.error('Use a NEW output directory; previous snapshots are immutable')
    r=build_legs(pd.read_csv(a.swings),pd.read_csv(a.ohlcv) if a.ohlcv else None,
                 as_of=a.as_of,config=LegConfig(rule_version=a.rule_version,atr_multiplier=a.atr_multiplier))
    out.mkdir(parents=True)
    for k,v in r.items():
        if isinstance(v,pd.DataFrame):v.to_csv(out/(k+'.csv'),index=False)
        elif isinstance(v,dict):(out/(k+'.json')).write_text(json.dumps(v,indent=2,default=str),encoding='utf-8')
    sensitivity(r['swing_leg']).to_csv(out/'sensitivity.csv',index=False)
    print(json.dumps(r['batch_log'],ensure_ascii=False))
if __name__=='__main__':main()

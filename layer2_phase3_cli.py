"""Offline replay into a new output directory; original pipeline/DB untouched."""
import argparse,json
from pathlib import Path
import pandas as pd
from structure_builder_sfs.phase3 import build_structures
from structure_builder_sfs.phase3_rules import RuleProvider
from structure_builder_sfs.phase3_store import StructureStore

def main():
    a=argparse.ArgumentParser()
    for flag in ('swings','ohlcv','as-of','output'):a.add_argument('--'+flag,required=True)
    a.add_argument('--rules');a.add_argument('--sqlite',action='store_true');args=a.parse_args()
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    p=RuleProvider(json.loads(Path(args.rules).read_text())) if args.rules else RuleProvider()
    result=build_structures(pd.read_csv(args.swings),pd.read_csv(args.ohlcv),as_of=args.as_of,provider=p)
    for name in ('market_structure','market_structure_event','audit'):result[name].to_csv(out/(name+'.csv'),index=False)
    for name in ('batch_log','rule_config'):(out/(name+'.json')).write_text(json.dumps(result[name],indent=2,default=str)+'\n')
    if args.sqlite:
        store=StructureStore(out/'structure_events.sqlite');store.save(result);store.close()
    print(json.dumps(result['batch_log'],indent=2))
if __name__=='__main__':main()

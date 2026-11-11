"""Offline Phase 4; accepts the complete Phase 3 event history, never the final projection."""
import argparse,json
from pathlib import Path
import pandas as pd
from structure_builder_sfs.phase4 import MajorContext,ContextRules,canonical
from structure_builder_sfs.phase4_store import ContextStore

def main():
    parser=argparse.ArgumentParser()
    for flag in ('events','ticker','timeframe','source-version','as-of','output'):parser.add_argument('--'+flag,required=True)
    parser.add_argument('--mode',required=True,choices=['EVER_CONFIRMED','ACTIVE','BOTH'],help='BOTH explicitly runs two separate queries; no default mode')
    parser.add_argument('--rules');parser.add_argument('--sqlite',action='store_true');a=parser.parse_args()
    rules=ContextRules(json.loads(Path(a.rules).read_text())) if a.rules else ContextRules()
    engine=MajorContext(pd.read_csv(a.events),rules);snap=engine.snapshot(a.as_of,ticker=a.ticker,timeframe=a.timeframe,source_version=a.source_version)
    modes=rules.get('query_modes') if a.mode=='BOTH' else [a.mode]
    contexts=[engine.context_from_snapshot(snap,mode=m) for m in modes]
    out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    (out/'snapshot.json').write_text(canonical(snap)+'\n')
    for c in contexts:(out/('context_'+c['query_mode']+'.json')).write_text(canonical(c)+'\n')
    pd.DataFrame(snap['classified_structures']).to_csv(out/'classified_structures.csv',index=False)
    pd.DataFrame(snap['major_sequence']).to_csv(out/'major_sequence.csv',index=False)
    if a.sqlite:
        store=ContextStore(out/'structure_context.sqlite');store.save(snap,contexts);store.close()
    print(json.dumps(dict(major=len(snap['major_sequence']),contexts=[{k:c[k] for k in ('query_mode','eligible_count','context_status','older_structure_id','latest_structure_id','is_long_candidate','reason_code')} for c in contexts]),indent=2))
if __name__=='__main__':main()

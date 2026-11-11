import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import pandas as pd
from structure_builder_sfs.phase4 import MajorContext,canonical
from structure_builder_sfs.phase4_store import ContextStore
out=ROOT/'reports/layer2_phase4';out.mkdir(parents=True,exist_ok=True)
store=ContextStore(out/'structure_context.sqlite');summary=[]
for ticker in ('HPG','FPT','VNM','VCB','SSI'):
    folder=ROOT/'reports/layer2_phase3'/ticker;events=pd.read_csv(folder/'market_structure_event.csv');engine=MajorContext(events)
    source=json.loads(events.iloc[0].payload_json)['after']['source_version']
    snap=engine.snapshot('2026-10-28 23:59:59+07:00',ticker=ticker,timeframe='15m',source_version=source)
    contexts=[engine.context_from_snapshot(snap,mode=m) for m in ('EVER_CONFIRMED','ACTIVE')]
    dest=out/ticker;dest.mkdir(exist_ok=True)
    (dest/'snapshot.json').write_text(canonical(snap)+'\n')
    for c in contexts:(dest/('context_'+c['query_mode']+'.json')).write_text(canonical(c)+'\n')
    pd.DataFrame(snap['classified_structures']).to_csv(dest/'classified_structures.csv',index=False)
    pd.DataFrame(snap['major_sequence']).to_csv(dest/'major_sequence.csv',index=False)
    store.save(snap,contexts);store.save(snap,contexts)
    rows=snap['classified_structures'];maj=snap['major_sequence'];record=dict(ticker=ticker,MAJOR=len(maj),INTERNAL=sum(r['classification']=='INTERNAL' for r in rows),UNCLASSIFIED=sum(r['classification']=='UNCLASSIFIED' for r in rows),MAJOR_UP=sum(r['structure_direction']=='UP' for r in maj),MAJOR_DOWN=sum(r['structure_direction']=='DOWN' for r in maj),MAJOR_BROKEN=sum(r['status']=='BROKEN' for r in maj),MAJOR_ACTIVE=sum(r['status']=='CONFIRMED' for r in maj))
    for c in contexts:
        record[c['query_mode']+'_pair']=' | '.join(r['start_swing_id']+'->'+r['end_swing_id']+' '+r['structure_direction']+' '+r['status'] for r in c['structures'])
    summary.append(record)
store.close();pd.DataFrame(summary).to_csv(out/'summary.csv',index=False);print(pd.DataFrame(summary).to_string(index=False))

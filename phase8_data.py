"""Local administrator CLI. No network or price assumptions."""
import argparse,json
import pandas as pd
from src.phase8.data import migrate,ingest,update_plan,SCHEMAS
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',default='data/state/qta_phase3_test.db');p.add_argument('--kind',choices=SCHEMAS);p.add_argument('--csv');p.add_argument('--allow-revisions',action='store_true');p.add_argument('--plan',action='store_true');a=p.parse_args()
    if a.plan:print(update_plan(a.db).to_csv(index=False))
    elif a.kind:
        if not a.csv:p.error('--kind requires --csv')
        print(json.dumps(ingest(a.db,a.kind,pd.read_csv(a.csv,keep_default_na=False),a.allow_revisions),ensure_ascii=False))
    else:print(json.dumps(migrate(a.db),ensure_ascii=False))

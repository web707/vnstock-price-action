"""Operational Phase4 SQLite replay CLI: DOES NOT delete or reset the existing DB.

Example: python -m reversal_setup_detector.run_phase4_store --db reports/layer3_phase4/custom.sqlite
Then rerun exactly the same command; inserted and updated should be zero.
Never point --db inside data/state or any upstream DB directory.
"""
import argparse,hashlib,json
from pathlib import Path
from datetime import datetime,timezone
from .phase4_config import ApprovedRules
from .calendar_phase3 import empirical_calendar
from .context import ContextProvider
from .lifecycle import scan_lifecycle
from .persistence import connect,persist_batch,statistics,export_long_setups,canonical_json
from .tools.report_phase1 import load_rows
from .tools.report_phase2 import events,SOURCE
ROOT=Path(__file__).resolve().parents[1]
TICKERS=('HPG','FPT','VNM','VCB','SSI')

def replay(db_path,long_path=None):
    db_path=Path(db_path).expanduser().resolve()
    src=ROOT/'data'
    if db_path.is_relative_to(src.resolve()):
        raise ValueError('REFUSE_OVERWRITE_UPSTREAM_DATA_DIR')
    phase1db=ROOT/'data/state/qta_phase3_test.db'
    if db_path==phase1db.resolve():
        raise ValueError('REFUSE_OVERWRITE_LAYER1_LAYER2_DB')
    r=ApprovedRules();results=[]
    for ticker in TICKERS:
        cal=empirical_calendar(r,ticker)
        results.append(scan_lifecycle(load_rows(ticker),r,cal,ContextProvider(events(ticker),rules=r),
           as_of=cal.end,ticker=ticker,timeframe='15m',source_version=SOURCE))
    conn=connect(db_path)
    try:
        result=persist_batch(conn,results)
        stats=statistics(conn);signals=export_long_setups(conn)
        all_rows=[]
        for table in ('reversal_setup','reversal_setup_event'):
            all_rows.append(dict(table=table,rows=[dict(x) for x in conn.execute(f'SELECT * FROM {table} ORDER BY 1')]))
        canonical_sha256=hashlib.sha256(canonical_json(all_rows).encode()).hexdigest()
    finally:conn.close()
    if long_path:
        p=Path(long_path).expanduser().resolve()
        if p.is_relative_to(src.resolve()):raise ValueError('REFUSE_WRITE_IN_UPSTREAM_DATA_DIR')
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(''.join(canonical_json(x)+'\n' for x in signals),encoding='utf-8')
    return dict(run_utc=datetime.now(timezone.utc).isoformat(),db=str(db_path),rule_version=r.version,
        config_hash=r.config_hash,calendar_source='UNVERIFIED',inserted=result['inserted'],
        updated=result['updated'],duplicates_prevented=result['duplicates_prevented'],
        events_inserted=result['events_inserted'],events_duplicates=result['events_duplicates'],
        db_statistics=stats,logical_sql_sha256=canonical_sha256)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db',default=str(ROOT/'reports/layer3_phase4/reversal_setup_phase4.sqlite'))
    p.add_argument('--long',default=None,help='Optional JSONL downstream export path')
    args=p.parse_args();print(json.dumps(replay(args.db,args.long),indent=2,ensure_ascii=False))
if __name__=='__main__':main()

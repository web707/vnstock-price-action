"""Actual Phase4 replay, two SQLite passes, LONG_SETUP, volume/timestamp audit.
Usage: python -m reversal_setup_detector.tools.report_phase4
Do not write to existing QTA upstream DB. Sidecar created under reports/layer3_phase4.
"""
from __future__ import annotations
import csv,json,sys,platform,hashlib,collections,statistics
from pathlib import Path
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from reversal_setup_detector.phase4_config import ApprovedRules
from reversal_setup_detector.calendar_phase3 import empirical_calendar
from reversal_setup_detector.context import ContextProvider
from reversal_setup_detector.lifecycle import scan_lifecycle
from reversal_setup_detector.persistence import connect,persist_batch,export_long_setups,statistics as db_stats,canonical_json
from reversal_setup_detector.tools.report_phase1 import load_rows,write_csv
from reversal_setup_detector.tools.report_phase2 import events,SOURCE
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'reports/layer3_phase4'
TICKERS=('HPG','FPT','VNM','VCB','SSI')
def dump(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
def slot_audit():
    slotrows=[];summary=[];timelines=[];tz_offset_ok=0;available_plus_15=0;nonzero=0
    for ticker in TICKERS:
        raw=load_rows(ticker)
        grouped=collections.defaultdict(list)
        for item in raw:
            t=datetime.fromisoformat(item['candle_time'])
            a=datetime.fromisoformat(item['available_at'])
            grouped[t.strftime('%H:%M')].append(Decimal(str(item['volume'])))
            tz_offset_ok+=(t.utcoffset()==timedelta(hours=7))
            available_plus_15+=(a==t+timedelta(minutes=15))
            nonzero+=Decimal(str(item['volume']))>0
            if t.strftime('%H:%M') in ('14:30','14:45'):
                timelines.append(dict(ticker=ticker,candle_time=item['candle_time'],volume=item['volume'],
                                      available_at=item['available_at'],open=item['open'],high=item['high'],
                                      low=item['low'],close=item['close']))
        for hm,vals in sorted(grouped.items()):
            zero=sum(x==0 for x in vals)
            slotrows.append(dict(ticker=ticker,slot=hm,observations=len(vals),
                mean_volume=round(sum(vals)/Decimal(len(vals)),2),median_volume=str(statistics.median(vals)),
                zero_volume_count=zero,zero_volume_pct=round(zero/len(vals)*100,2)))
        summary.append(dict(ticker=ticker,total=len(raw),num_1445=len(grouped['14:45']),zero_1445=sum(x==0 for x in grouped['14:45']),
            mean_volume_1445=round(sum(grouped['14:45'])/len(grouped['14:45']),2),
            num_1430=len(grouped.get('14:30',[]))))
    return dict(rows=slotrows,summary=summary,slot_1445_details=timelines,
        total_candles=sum(x['total'] for x in summary),timezone_plus07_records=tz_offset_ok,
        available_equals_timestamp_plus_15min=available_plus_15,nonzero_volume_records=nonzero,
        contract='INTERNAL_CONSISTENCY_NOT_INDEPENDENT_SOURCE_PROOF',
        auction_label_status='UNVERIFIED',
        official_ATC_hours='14:30-14:45, HOSE; 14:45 records cannot be asserted ATC if timestamp is bar open')

def table_hash(conn):
    data=[]
    for table in ('reversal_setup','reversal_setup_event'):
        rows=[dict(x) for x in conn.execute(f'SELECT * FROM {table} ORDER BY 1')]
        data.append(dict(table=table,rows=rows))
    return hashlib.sha256(canonical_json(data).encode()).hexdigest()

def main():
    OUT.mkdir(exist_ok=True,parents=True)
    r=ApprovedRules()
    print('PHASE4 REPLAY RUN START UTC',datetime.now(timezone.utc).isoformat(),flush=True)
    print('Platform',platform.platform(),'Python',sys.version.split()[0],flush=True)
    print('Baseline Phase3 replay; approved D04 true, D03 conditional. 14:45 auction source label UNVERIFIED',flush=True)
    print('rule_version',r.version,'config_hash',r.config_hash,'max_wait_candles',r.get('max_wait_candles'),
        'ratio inclusive',r.get('body_ratio_min'),r.get('body_ratio_max'),flush=True)
    audit=slot_audit();dump('intraday_volume_audit.json',audit)
    write_csv(OUT/'volume_by_ticker_slot.csv',audit['rows'])
    write_csv(OUT/'late_slot_observations.csv',audit['slot_1445_details'])
    print('VOLUME_AUDIT','total',audit['total_candles'],'internal_label_plus15',audit['available_equals_timestamp_plus_15min'],
          'source_confirmed',False,flush=True)
    for x in audit['summary']:print('VOLUME',x,flush=True)
    replay=[]
    for ticker in TICKERS:
        cal=empirical_calendar(r,ticker)
        if cal.verified:raise AssertionError('PROVIDER_CALENDAR_MUST_REMAIN_UNVERIFIED')
        z=scan_lifecycle(load_rows(ticker),r,cal,ContextProvider(events(ticker),rules=r),
          as_of=cal.end,ticker=ticker,timeframe='15m',source_version=SOURCE)
        replay.append(z)
        print('SCAN',ticker,z['metrics'],flush=True)
        for s in z['candidates']:
            print('CANDIDATE',ticker,s['setup_id'],s['red_candle_times'],s['context_structure_ids'],
                'status',s['status'],'reason',s['reason_code'],'G',s['reversal_candle_time'],
                'ratio',s['body_ratio'],'window_crosses_session',s['window_crosses_session'],
                'context_age_bars',s['context_age_bars'],flush=True)
    db=OUT/'reversal_setup_phase4.sqlite'
    if db.exists():db.unlink()  # reproducible from zero: two passes in THIS run
    conn=connect(db);passes=[]
    try:
        for num in (1,2):
            result=persist_batch(conn,replay)
            digest=table_hash(conn)
            stats=db_stats(conn)
            rec=dict(pass_no=num,**{k:v for k,v in result.items() if k!='actions'},
                table_snapshot_sha256=digest,db=stats)
            passes.append(rec)
            print('SQL_PASS',num,rec,flush=True)
            for a in result['actions']:
                print('SQL_ACTION',num,canonical_json(a),flush=True)
        if passes[0]['table_snapshot_sha256']!=passes[1]['table_snapshot_sha256']:
            raise AssertionError('NOT_IDEMPOTENT_TABLE_STATE')
        if passes[1]['inserted']!=0 or passes[1]['updated']!=0 or passes[1]['events_inserted']!=0:
            raise AssertionError('DUPLICATES_ON_SECOND_PASS')
        signals=export_long_setups(conn);states=db_stats(conn)
        assert states['setups']==4 and states['events']==8 and states['signals']==2
        assert states['by_status']=={'FOUND':2,'EXPIRED':1,'INVALIDATED':1} or states['by_status']=={'EXPIRED':1,'FOUND':2,'INVALIDATED':1}
        assert {x['ticker'] for x in signals}=={'FPT','SSI'}
        assert len([x for x in signals if x['ticker']=='SSI' and Decimal(x['body_ratio'])==Decimal('1.0') and x['window_crosses_session']])==1
        dump('SQL_TWO_PASS_METRICS.json',dict(passes=passes,source='REAL_SNAPSHOT',
            total_candles=sum(x['metrics']['total_candles_processed'] for x in replay),
            valid_red_triplets=sum(x['metrics']['valid_red_triplets'] for x in replay),
            invalid_candles=sum(x['metrics']['invalid_candles'] for x in replay),
            data_gaps=sum(x['metrics']['data_gaps'] for x in replay),
            found_rate=states['by_status']['FOUND']/states['setups'],
            no_orders_or_fills=True,calendar_source='UNVERIFIED'))
        dump('LONG_SETUP.json',signals)
        (OUT/'LONG_SETUP.jsonl').write_text(''.join(canonical_json(x)+'\n' for x in signals),encoding='utf-8')
        print('LONG_SETUP_COUNT',len(signals),flush=True)
        for x in signals:print('LONG_SETUP',canonical_json(x),flush=True)
        print('IDEMPOTENCY_PASS unchanged_sql_tables_sha256',passes[1]['table_snapshot_sha256'],flush=True)
        candidate_rows=[]
        for z in replay:
            for s in z['candidates']:
                candidate_rows.append(dict(ticker=s['ticker'],setup_id=s['setup_id'],
                    r1=s['red_candle_times'][0],r2=s['red_candle_times'][1],r3=s['red_candle_times'][2],
                    structure_1=s['context_structure_ids'][0],structure_2=s['context_structure_ids'][1],
                    status=s['status'],reason_code=s['reason_code'],G=s['reversal_candle_time'],
                    body_ratio=s['body_ratio'],window_crosses_session=s['window_crosses_session'],
                    context_age_bars=s['context_age_bars'],available_at=s['available_at'],
                    calendar_source_verification='UNVERIFIED'))
        write_csv(OUT/'candidate_phase4.csv',candidate_rows)
        dump('candidate_phase4.json',candidate_rows)
    finally:conn.close()
    print('PHASE4 REPLAY RUN END UTC',datetime.now(timezone.utc).isoformat(),flush=True)

if __name__=='__main__':main()

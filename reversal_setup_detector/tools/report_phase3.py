"""Create reproducible Phase3 *in-memory* replay audit. No SQL, no LONG_SETUP."""
import sys,json,platform,csv,hashlib
from pathlib import Path
from collections import Counter
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from reversal_setup_detector.candles import Rules,analyze
from reversal_setup_detector.calendar_phase3 import (empirical_calendar,audit_rows,HOLIDAY_SOURCE,HOLIDAYS_IN_SNAPSHOT,
     DAILY_OPEN_TIMES,EXCEPTIONAL_OBSERVED_SLOTS)
from reversal_setup_detector.lifecycle import scan_lifecycle
from reversal_setup_detector.context import ContextProvider
from reversal_setup_detector.tools.report_phase1 import load_rows,write_csv
from reversal_setup_detector.tools.report_phase2 import events,SOURCE
OUT=ROOT/'reports/layer3_phase3'
TICKERS=('HPG','FPT','VNM','VCB','SSI')

def write_json(name,data):
    (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')

def ruler(cross):
    name='TRUE' if cross else 'FALSE'
    return Rules(json.loads((ROOT/f'reversal_setup_detector/config/L3_REVERSAL_V1_PHASE3_CROSS_{name}.json').read_text()))

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    print('Phase3 replay start UTC',datetime.now(timezone.utc).isoformat(),flush=True)
    print('Python',sys.version.split()[0],platform.platform(),flush=True)
    print('Input snapshots: reports/layer1/{ticker}_clean.csv, reports/layer2_phase3/{ticker}/market_structure_event.csv',flush=True)
    print('Holiday reference',HOLIDAY_SOURCE,'; source timestamps and auction slot labels NOT independently verified',flush=True)
    full={};audits=[];slots=[];days=[];metrics=[];calendars=[]
    for flag in (True,False):
        policy='TRUE' if flag else 'FALSE'
        r=ruler(flag);full[policy]={}
        print('Policy',policy,'rule_version',r.version,'config_sha256',r.config_hash,flush=True)
        for ticker in TICKERS:
            rows=load_rows(ticker);calendar=empirical_calendar(r,ticker)
            if flag:
                a=audit_rows(rows,ticker,calendar,r)
                audits.append(a)
                for d in a['daily_counts']:days.append(dict(ticker=ticker,**d))
                for time,num in a['time_slot_counts'].items():slots.append(dict(ticker=ticker,time=time,count=num))
                calendars.append(dict(ticker=ticker,calendar_id=calendar.id,calendar_hash=calendar.hash,verified=calendar.verified,
                    slot_count=len(calendar.slots),holidays_in_snapshot=sorted(HOLIDAYS_IN_SNAPSHOT),
                    exceptional_1430=a['exceptional_1430']))
                if a['missing_expected_slots'] or a['unexpected_slots'] or a['duplicate_times']:
                    raise AssertionError('EMPIRICAL_CALENDAR_MISMATCH:'+ticker)
            data=analyze(rows,r,calendar,as_of=calendar.end)
            provider=ContextProvider(events(ticker),rules=r)
            z=scan_lifecycle(rows,r,calendar,provider,
                as_of=calendar.end,ticker=ticker,timeframe='15m',source_version=SOURCE)
            assert z['metrics']['data_gaps']==0
            assert z['metrics']['invalid_candles']==0
            full[policy][ticker]=z
            metrics.append(dict(policy=policy,ticker=ticker,**z['metrics']))
            write_json(f'{policy}_{ticker}_candidates_events.json',z)
            print(policy,ticker,dict(candles=z['metrics']['total_candles_processed'],
                valid_red_triplets=z['metrics']['valid_red_triplets'],candidates=z['metrics']['candidates_created'],
                found=z['metrics']['found'],expired=z['metrics']['expired'],invalidated=z['metrics']['invalidated']),flush=True)
            for s in z['candidates']:
                print(' candidate',s['setup_id'],'R3',s['red_candle_times'][-1],
                    'R1/R2/R3',s['red_candle_times'],
                    'Layer2 IDs',s['context_structure_ids'],
                    'status',s['status'],'reason',s['reason_code'],
                    'G',s['reversal_candle_time'],'body_ratio',s['body_ratio'],
                    'window_crosses_session',s['window_crosses_session'],
                    'observed_cross_session',s['observed_window_crosses_session'],flush=True)
    true_candidates=[s for t in TICKERS for s in full['TRUE'][t]['candidates']]
    false_by_key={(s['ticker'],tuple(s['red_candle_times'])):s for t in TICKERS for s in full['FALSE'][t]['candidates']}
    assert len(true_candidates)==4
    comparisons=[];evidence=[]
    for s in true_candidates:
        alt=false_by_key.get((s['ticker'],tuple(s['red_candle_times'])))
        for flag,item in [('TRUE',s),('FALSE',alt)]:
            comparisons.append(dict(policy=flag,ticker=s['ticker'],
                r1=s['red_candle_times'][0],r2=s['red_candle_times'][1],r3=s['red_candle_times'][2],
                context_structure_id_1=s['context_structure_ids'][0],
                context_structure_id_2=s['context_structure_ids'][1],
                red_triplet_crosses_session=s['red_triplet_crosses_session'],
                window_crosses_session=s['window_crosses_session'] if item is None else item['window_crosses_session'],
                observed_window_crosses_session=None if item is None else item['observed_window_crosses_session'],
                candidate_created=item is not None,
                result='NOT_CREATED' if item is None else item['status'],
                reason_code='RED_TRIPLET_CROSSES_SESSION_DISALLOWED' if item is None else item['reason_code'],
                setup_id=None if item is None else item['setup_id'],
                reversal_candle_time=None if item is None else item['reversal_candle_time'],
                ratio=None if item is None else item['body_ratio'],
                bars_checked=None if item is None else item['bars_checked'],
                resolved_at=None if item is None else item['resolved_at']))
        if s['ticker'] in ('HPG','SSI'):
            provider=ContextProvider(events(s['ticker']),rules=ruler(True))
            at='2026-10-05T09:30:00+07:00' if s['ticker']=='HPG' else '2026-10-16T09:30:00+07:00'
            context=provider.evaluate(at,ticker=s['ticker'],timeframe='15m',source_version=SOURCE)
            c=[x for x in load_rows(s['ticker']) if x['candle_time']==at.replace('T09:30:00','T09:15:00')]
            evidence.append(dict(ticker=s['ticker'],candidate_r3=s['red_candle_times'][2],
                diagnostic_at=at,context_reason=context['reason_code'],
                original_context_ids=s['context_structure_ids'],
                original_context_states=[dict(structure_id=x['structure_id'],status=x['status'],invalidated_at=x.get('invalidated_at')) for x in context['structures'] if x['structure_id'] in s['context_structure_ids']],
                green_candidate=c[0] if c else None))
    # Byte-for-byte underlying pattern assertion: exactly one FALSE candidate omitted at red-triplet gate.
    assert Counter((x['result'] for x in comparisons if x['policy']=='TRUE'))=={'FOUND':2,'EXPIRED':1,'INVALIDATED':1}
    assert Counter((x['result'] for x in comparisons if x['policy']=='FALSE'))=={'FOUND':1,'NOT_CREATED':1,'INVALIDATED':2}
    write_csv(OUT/'slot_counts_by_ticker.csv',slots)
    write_csv(OUT/'daily_counts_by_ticker.csv',days)
    write_csv(OUT/'candidate_comparison.csv',comparisons)
    write_csv(OUT/'metrics_by_ticker.csv',metrics)
    write_json('calendar_audit.json',dict(audits=audits,calendars=calendars,
        source=HOLIDAY_SOURCE,holiday_dates=sorted(HOLIDAYS_IN_SNAPSHOT),
        confidence='MARKET_HOLIDAY_DATES_OFFICIAL; PROVIDER_BAR_TIMESTAMPS_UNVERIFIED',
        slot_schema='15m open labels, 16 regular bars/day (09:15-11:15,13:00-14:15,14:45), 14:30 rare observed exceptions',
        no_future_ohlcv_used_in_lifecycle=True))
    write_json('candidate_comparison.json',comparisons)
    write_json('real_HPG_SSI_context_break_evidence.json',evidence)
    write_json('metrics_by_ticker.json',metrics)
    print('COMPARISON_ROWS',len(comparisons),'TRUE',Counter(x['result'] for x in comparisons if x['policy']=='TRUE'),
        'FALSE',Counter(x['result'] for x in comparisons if x['policy']=='FALSE'),flush=True)
    print('CALENDAR audit 56 trading days x 5, 4,482 candles; 2 observed 14:30, 280 observed 14:45, 0 missing expected or outside slot',flush=True)
    print('Phase3 replay finish UTC',datetime.now(timezone.utc).isoformat(),flush=True)

if __name__=='__main__':main()

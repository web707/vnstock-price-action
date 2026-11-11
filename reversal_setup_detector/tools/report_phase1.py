"""Research candle-only audit. Five-slot windows below are diagnostics, not setup lifecycle."""
import csv
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from reversal_setup_detector import Rules, Calendar, analyze

def load_rows(ticker):
    with (ROOT/f'reports/layer1/{ticker}_clean.csv').open() as f:
        return [dict(ticker=ticker,timeframe='15m',candle_time=x['Datetime'],available_at=x['available_time'],**{k:x[k.title()] for k in ['open','high','low','close','volume']}) for x in csv.DictReader(f)]

def write_csv(path,rows):
    if not rows: path.write_text('',encoding='utf-8');return
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def main():
    out=ROOT/'reports/layer3_phase1';out.mkdir(parents=True,exist_ok=True)
    r=Rules();cal=Calendar.template(r,'2026-08-07 00:00+07:00','2026-10-29 00:00+07:00')
    (out/'calendar_snapshot.json').write_text(json.dumps(dict(calendar_id=cal.id,verified=cal.verified,coverage_start=cal.start,coverage_end=cal.end,calendar_hash=cal.hash,slots=cal.slots),default=str,indent=2))
    summaries=[];windows=[]
    for ticker in ['HPG','FPT','VNM','VCB','SSI']:
        rows=load_rows(ticker);z=analyze(rows,r,cal,as_of=cal.end)
        (out/f'{ticker}_candles_patterns.json').write_text(json.dumps(z,indent=2,ensure_ascii=False))
        cs=r.as_dict();cs.update(rule_version='L3_REVERSAL_V1_NO_CROSS_DIAGNOSTIC',allow_cross_session_sequences=False)
        no_cross=analyze(rows,Rules(cs),cal,as_of=cal.end)
        by_index={c['calendar_index']:c for c in z['candles'] if c['valid']}
        ticker_windows=[]
        for p in z['triplets']:
            n=p['candles'][-1]['calendar_index'];indices=list(range(n+1,n+1+r.get('max_wait_candles')))
            slots=[cal.slots[j] for j in indices if j<len(cal.slots)]
            same_coverage=len(slots)==r.get('max_wait_candles') and all(s['close_at']<=cal.end for s in slots)
            observed=[by_index[j] for j in indices if j in by_index]
            crosses=any(s['session_id']!=p['candles'][-1]['session_id'] for s in slots)
            record=dict(ticker=ticker,pattern_id=p['pattern_id'],r3=p['red_candle_times'][-1],calendar_verified=False,
                expected_window_cross_session=crosses,expected_window_cross_date=any(s['open_at'].date().isoformat()!=p['red_candle_times'][-1][:10] for s in slots),
                complete_5_valid_bars=same_coverage and len(observed)==r.get('max_wait_candles'),
                observed_valid_slots=len(observed),window_end=slots[-1]['close_at'].isoformat() if slots else None)
            ticker_windows.append(record);windows.append(record)
        summaries.append(dict(ticker=ticker,**z['metrics'],no_cross_session_triplets=len(no_cross['triplets']),
            diagnostic_windows=len(ticker_windows),windows_cross_session=sum(w['expected_window_cross_session'] for w in ticker_windows),
            windows_cross_date=sum(w['expected_window_cross_date'] for w in ticker_windows),
            windows_complete=sum(w['complete_5_valid_bars'] for w in ticker_windows),
            complete_windows_cross_session=sum(w['complete_5_valid_bars'] and w['expected_window_cross_session'] for w in ticker_windows)))
        print(json.dumps(summaries[-1]),flush=True)
    write_csv(out/'summary.csv',summaries);write_csv(out/'five_slot_window_diagnostics.csv',windows)
    (out/'summary.json').write_text(json.dumps(summaries,indent=2))
if __name__=='__main__':main()

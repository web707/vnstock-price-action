"""Phase-3 research calendar from snapshot slot-audit plus official 2026 exchange holidays.

This is *not* an independently verified provider timestamp / auction calendar.
The isolated 14:30 records on 2026-08-20 for VCB/SSI are explicit, documented
exceptions, not extrapolated to every day and not silently dropped.
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
import json
from .candles import Calendar

HOLIDAYS_IN_SNAPSHOT = frozenset({'2026-08-31', '2026-09-01', '2026-09-02'})
HOLIDAY_SOURCE = 'https://www.hsx.vn/vi/tin-tuc/hose-thong-bao-lich-nghi-giao-dich-nam-2026/2437411'
START='2026-08-07T00:00:00+07:00'
END='2026-10-29T00:00:00+07:00'
DAILY_OPEN_TIMES = (
    '09:15','09:30','09:45','10:00','10:15','10:30',
    '10:45','11:00','11:15','13:00','13:15','13:30',
    '13:45','14:00','14:15','14:45',
)
EXCEPTIONAL_OBSERVED_SLOTS = {
    'VCB': {'2026-08-20': ('14:30',)},
    'SSI': {'2026-08-20': ('14:30',)},
}

def trading_dates(start=START,end=END):
    d=datetime.fromisoformat(start)
    stop=datetime.fromisoformat(end)
    while d < stop:
        if d.weekday()<5 and d.date().isoformat() not in HOLIDAYS_IN_SNAPSHOT:
            yield d
        d+=timedelta(days=1)

def empirical_calendar(rules,ticker,*,start=START,end=END):
    """Versioned replay input; holiday closes externally sourced, candle slots empirical.

    The 09:00 absence is NOT interpreted as missing data; the isolated 14:30
    observed candles are included for their precise ticker/date only.
    """
    if rules.get('timeframe')!='15m' or rules.get('timestamp_label')!='open':
        raise ValueError('PHASE3_EMPIRICAL_CALENDAR_REQUIRES_15M_OPEN')
    slots=[]
    for d in trading_dates(start,end):
        date=d.date().isoformat()
        exceptions=EXCEPTIONAL_OBSERVED_SLOTS.get(ticker,{}).get(date,())
        for hm in sorted(set(DAILY_OPEN_TIMES).union(exceptions)):
            h,m=map(int,hm.split(':'))
            open_at=d.replace(hour=h,minute=m)
            slots.append(dict(open_at=open_at,close_at=open_at+rules.duration,
                session_id=f'{date}:{"AM" if h<12 else "PM"}'))
    return Calendar(slots,rules,calendar_id=f'EMPIRICAL_15M_20260807_20261028_{ticker}_V1_UNVERIFIED',
                    verified=False,coverage_start=start,coverage_end=end)

def audit_rows(rows,ticker,calendar,rules):
    by_slot=Counter();daily=Counter();rawtimes=set();duplicate=[]
    for x in rows:
        t=rules.timestamp(x['candle_time'])
        stamp=t.isoformat()
        if stamp in rawtimes:duplicate.append(stamp)
        rawtimes.add(stamp)
        by_slot[t.strftime('%H:%M')]+=1
        daily[t.date().isoformat()]+=1
    expected_daily=Counter(x['open_at'].date().isoformat() for x in calendar.slots)
    missing=[x['open_at'].isoformat() for x in calendar.slots if x['open_at'].isoformat() not in rawtimes]
    outside=[x for x in sorted(rawtimes) if rules.timestamp(x) not in calendar.by_time]
    return dict(ticker=ticker,total_candles=len(rows),trading_days=len(daily),
                time_slot_counts={t:by_slot[t] for t in sorted(set(DAILY_OPEN_TIMES)|{'09:00','14:30'})},
                daily_counts=[dict(date=d,observed=daily[d],expected=expected_daily[d]) for d in sorted(set(daily)|set(expected_daily))],
                daily_count_distribution=dict(sorted(Counter(daily.values()).items())),
                exceptional_1430=[x for x in sorted(rawtimes) if x[11:16]=='14:30'],
                missing_expected_slots=missing,unexpected_slots=outside,duplicate_times=duplicate,
                expected_total_slots=len(calendar.slots),calendar_id=calendar.id,
                calendar_hash=calendar.hash,calendar_verified=calendar.verified,
                methodological_limit='Snapshot-calibrated slot model; provider timestamps, auction labelling and actual feed publication not independently verified')

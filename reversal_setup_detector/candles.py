"""Pure point-in-time candle scanner. Calendar evidence is supplied, never inferred from bars."""
import copy
import hashlib
import json
import re
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

CONFIG = Path(__file__).parent / 'config/L3_REVERSAL_V1.json'

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()

class Rules:
    def __init__(self, config=None):
        baseline = json.loads(CONFIG.read_text(encoding='utf-8'))
        self._c = copy.deepcopy(baseline if config is None else config)
        if set(self._c) != set(baseline):
            raise ValueError('CONFIG_FIELDS_MISMATCH')
        if not isinstance(self._c['rule_version'], str) or not self._c['rule_version']:
            raise ValueError('RULE_VERSION_REQUIRED')
        if self._c['rule_version'] == baseline['rule_version'] and self._c != baseline:
            raise ValueError('NEW_RULE_VERSION_REQUIRED')
        match = re.fullmatch(r'([1-9][0-9]*)m', self._c['timeframe'])
        if not match:
            raise ValueError('TIMEFRAME_MINUTES_REQUIRED')
        self.duration = timedelta(minutes=int(match[1]))
        for k in ['allow_cross_session_sequences', 'red_candle_1_requires_body_gt_total_wick',
                  'red_candle_2_requires_body_gt_total_wick', 'red_candle_3_requires_body_gt_total_wick']:
            if not isinstance(self._c[k], bool):
                raise ValueError('BOOLEAN_REQUIRED:' + k)
        for k in ['availability_policy','missing_available_at','duplicate_policy','invalid_policy','unknown_calendar_policy']:
            if self._c[k] != baseline[k]:
                raise ValueError('UNSUPPORTED_POLICY:' + k)
        if self._c['timestamp_label'] not in ['open', 'close']:
            raise ValueError('TIMESTAMP_LABEL_INVALID')
        ZoneInfo(self._c['timezone']); ZoneInfo(self._c['naive_timezone'])
        if type(self._c['max_wait_candles']) is not int or self._c['max_wait_candles'] < 1:
            raise ValueError('POSITIVE_WINDOW_REQUIRED')
        if self._c['calendar_template']['verified'] is not False:
            raise ValueError('TEMPLATE_CANNOT_CLAIM_VERIFIED_CALENDAR')
    def get(self, key): return copy.deepcopy(self._c[key])
    def as_dict(self): return copy.deepcopy(self._c)
    @property
    def version(self): return self._c['rule_version']
    @property
    def config_hash(self): return digest(self._c)
    def timestamp(self, value):
        if value is None or isinstance(value, (int, float, bool)):
            raise ValueError('INVALID_TIMESTAMP')
        t = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        if t.tzinfo is None: t = t.replace(tzinfo=ZoneInfo(self.get('naive_timezone')))
        return t.astimezone(ZoneInfo(self.get('timezone')))

class Calendar:
    """Explicit expected slots, with coverage and evidence status. No market-rule guessing."""
    def __init__(self, slots, rules, *, calendar_id, verified, coverage_start, coverage_end):
        self.id = calendar_id; self.verified = verified
        self.binding = (rules.get('timeframe'), rules.get('timestamp_label'), rules.get('timezone'))
        self.start = rules.timestamp(coverage_start); self.end = rules.timestamp(coverage_end)
        if not calendar_id or not isinstance(verified, bool) or self.start >= self.end:
            raise ValueError('INVALID_CALENDAR_METADATA')
        self.slots = []
        for x in slots:
            a, b = rules.timestamp(x['open_at']), rules.timestamp(x['close_at'])
            if not self.start <= a < b <= self.end or not x.get('session_id'):
                raise ValueError('INVALID_CALENDAR_SLOT')
            self.slots.append(dict(open_at=a, close_at=b, session_id=str(x['session_id'])))
        self.slots.sort(key=lambda x: x['open_at'])
        if any(a['close_at'] > b['open_at'] for a,b in zip(self.slots,self.slots[1:])):
            raise ValueError('OVERLAPPING_CALENDAR_SLOTS')
        key = 'open_at' if rules.get('timestamp_label') == 'open' else 'close_at'
        self.by_time = {x[key]: i for i,x in enumerate(self.slots)}
        self.times = [x[key] for x in self.slots]
        self.hash = digest(dict(id=self.id, verified=self.verified, start=self.start, end=self.end, slots=self.slots))
    @classmethod
    def template(cls, rules, start, end):
        """Research fallback only: upstream weekday/session template, not a verified exchange calendar."""
        cfg = rules.get('calendar_template'); a=rules.timestamp(start); b=rules.timestamp(end)
        slots=[]; day=a.replace(hour=0,minute=0,second=0,microsecond=0)
        while day < b:
            if day.weekday() in cfg['weekdays']:
                for begin, finish, label in cfg['sessions']:
                    h,m=map(int,begin.split(':')); t=day.replace(hour=h,minute=m)
                    h,m=map(int,finish.split(':')); stop=day.replace(hour=h,minute=m)
                    while t+rules.duration <= stop:
                        if a <= t and t+rules.duration <= b:
                            slots.append(dict(open_at=t,close_at=t+rules.duration,session_id=f'{day.date()}:{label}'))
                        t += rules.duration
            day += timedelta(days=1)
        return cls(slots,rules,calendar_id=cfg['id'],verified=cfg['verified'],coverage_start=a,coverage_end=b)

def number(value):
    if value is None or isinstance(value,bool): raise ValueError('INVALID_NUMBER')
    try: d=Decimal(str(value))
    except (InvalidOperation,ValueError): raise ValueError('INVALID_NUMBER')
    if not d.is_finite(): raise ValueError('NONFINITE_NUMBER')
    return d

def morphology(row):
    """Decimal arithmetic: strict comparisons, no tolerance or rounding added to candle rules."""
    o,h,l,c,v=(number(row.get(k)) for k in ['open','high','low','close','volume'])
    if min(o,h,l,c) <= 0: raise ValueError('NONPOSITIVE_PRICE')
    if h < max(o,c) or l > min(o,c) or h < l: raise ValueError('INVALID_OHLC')
    if v < 0: raise ValueError('NEGATIVE_VOLUME')
    body=abs(c-o); upper=h-max(o,c); lower=min(o,c)-l
    return dict(body=body,upper_wick=upper,lower_wick=lower,total_wick=upper+lower,
                color='RED' if c<o else 'GREEN' if c>o else 'DOJI',strong=body>upper+lower)

def analyze(rows, rules, calendar, *, as_of):
    """Snapshot API, independent streams; invalid known candles remain barriers.

    A row becomes usable at max(actual calendar close, source available_at).
    Future rows are excluded before duplicates/validation can affect past results.
    Unknown-time/unidentified rows fail the contract rather than being silently dropped.
    Results are plain JSON data. Pending/missing slots prevent bridging late data.
    """
    at=rules.timestamp(as_of)
    if calendar.binding != (rules.get('timeframe'), rules.get('timestamp_label'), rules.get('timezone')):
        raise ValueError('CALENDAR_RULE_BINDING_MISMATCH')
    if not calendar.start <= at <= calendar.end: raise ValueError('AS_OF_OUTSIDE_CALENDAR_COVERAGE')
    groups=defaultdict(list)
    for source_index, raw in enumerate(rows):
        # No OHLC inspection or global row count enters a past result before availability.
        t=rules.timestamp(raw.get('candle_time'))
        slot_index=calendar.by_time.get(t)
        slot=calendar.slots[slot_index] if slot_index is not None else None
        close=slot['close_at'] if slot else t+(rules.duration if rules.get('timestamp_label')=='open' else timedelta(0))
        supplied=raw.get('available_at')
        availability=rules.timestamp(supplied) if supplied not in (None,'') else close
        effective=max(close,availability)
        if effective>at: continue
        ticker=raw.get('ticker'); timeframe=raw.get('timeframe')
        if not isinstance(ticker,str) or not ticker.strip() or not isinstance(timeframe,str) or not timeframe:
            raise ValueError('STREAM_IDENTITY_REQUIRED')
        groups[(ticker,timeframe)].append((t,source_index,raw,slot_index,effective,supplied is None or supplied==''))
    candles=[]; triplets=[]; gaps=[]; diagnostics=[]
    for (ticker,timeframe), entries in sorted(groups.items()):
        entries.sort(key=lambda x:(x[0],x[1])); multiplicity=Counter(x[0] for x in entries)
        sequence=[]
        for t,index,raw,idx,effective,derived in entries:
            reasons=[]; features=None
            if timeframe!=rules.get('timeframe'): reasons.append('TIMEFRAME_MISMATCH')
            if idx is None: reasons.append('CANDLE_OUTSIDE_CALENDAR')
            if multiplicity[t]>1: reasons.append('DUPLICATE_CANDLE_TIME')
            try: features=morphology(raw)
            except ValueError as e: reasons.append(str(e))
            item=dict(ticker=ticker,timeframe=timeframe,candle_time=t.isoformat(),available_at=effective.isoformat(),
                      calendar_index=idx,session_id=calendar.slots[idx]['session_id'] if idx is not None else None,
                      valid=not reasons,reason_codes=reasons,availability_derived=derived,
                      **{k:raw.get(k) for k in ['open','high','low','close','volume']})
            if features: item.update({k:str(v) if isinstance(v,Decimal) else v for k,v in features.items()})
            candles.append(item); sequence.append(item)
            if reasons: diagnostics.append(dict(ticker=ticker,timeframe=timeframe,candle_time=t.isoformat(),reason_code='INVALID_CANDLE_DATA',details=reasons))
        # Between observed known times only: do not claim completeness before/after input coverage.
        for left,right in zip(sequence,sequence[1:]):
            a=rules.timestamp(left['candle_time']); b=rules.timestamp(right['candle_time'])
            missing=calendar.times[bisect_right(calendar.times,a):bisect_left(calendar.times,b)]
            if missing:
                gaps.append(dict(ticker=ticker,timeframe=timeframe,left=a.isoformat(),right=b.isoformat(),
                    known_at=max(left['available_at'],right['available_at']),missing_times=[x.isoformat() for x in missing],
                    reason_code='DATA_GAP_IN_CANDLE_SEQUENCE' if calendar.verified else 'UNVERIFIED_CALENDAR_GAP',verified=calendar.verified))
        for i in range(2,len(sequence)):
            triple=sequence[i-2:i+1]
            if not all(x['valid'] for x in triple): continue
            indices=[x['calendar_index'] for x in triple]
            if indices!=list(range(indices[0],indices[0]+3)): continue
            crosses=len({x['session_id'] for x in triple})>1
            if crosses and not rules.get('allow_cross_session_sequences'): continue
            if not all(x['color']=='RED' for x in triple): continue
            if any(rules.get(f'red_candle_{j}_requires_body_gt_total_wick') and not x['strong'] for j,x in enumerate(triple,1)): continue
            times=[x['candle_time'] for x in triple]
            triplets.append(dict(pattern_id=digest([ticker,timeframe,*times,rules.version,rules.config_hash,calendar.hash]),
                ticker=ticker,timeframe=timeframe,rule_version=rules.version,config_hash=rules.config_hash,
                red_candle_times=times,candles=copy.deepcopy(triple),available_at=max(x['available_at'] for x in triple),
                cross_session=crosses,cross_date=len({x[:10] for x in times})>1,
                calendar_id=calendar.id,calendar_verified=calendar.verified,reason_code='THREE_RED_CANDLE_PATTERN_FOUND'))
    return dict(rule_version=rules.version,config_hash=rules.config_hash,as_of=at.isoformat(),
                calendar_id=calendar.id,calendar_hash=calendar.hash,calendar_verified=calendar.verified,
                candles=candles,triplets=triplets,gaps=gaps,diagnostics=diagnostics,
                metrics=dict(known_candles=len(candles),invalid_candles=sum(not x['valid'] for x in candles),
                    gaps=len(gaps),missing_slots=sum(len(x['missing_times']) for x in gaps),valid_red_triplets=len(triplets),
                    cross_session_triplets=sum(x['cross_session'] for x in triplets),cross_date_triplets=sum(x['cross_date'] for x in triplets)))

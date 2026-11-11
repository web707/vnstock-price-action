"""SFS v1.0 Phase 2: immutable legs, never market structures.

Replay confirmation batches, order eligible prices by extreme_time, emit once.
If late input would split an already published leg, quarantine that new input
(DATA_ORDER_AMBIGUOUS); an explicit new source/version rebuild is required.
No original row is deleted. Invalid later batches cannot erase published legs.
Percent amplitude is a FRACTION (0.1 = 10%). Duration minutes is wall-clock;
bar count is NULL unless a contiguous 15-minute calendar is actually present.
"""
from dataclasses import dataclass, asdict, field, replace
from decimal import Decimal
import hashlib
import json
import math
import time
import pandas as pd
from .phase1 import Config, build_labels, ts

@dataclass(frozen=True)
class LegConfig:
    rule_version: str = 'sfs-layer2-phase2-DRAFT-001'
    atr_multiplier: float = 3.0
    labeling: Config = field(default_factory=Config)
    def __post_init__(self):
        if not self.rule_version.strip():
            raise ValueError('rule_version required')
        if isinstance(self.atr_multiplier, bool) or not math.isfinite(self.atr_multiplier) or self.atr_multiplier <= 0:
            raise ValueError('atr_multiplier must be finite and positive')
    @property
    def config_hash(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()

COLUMNS = ['leg_id','ticker','timeframe','start_swing_id','end_swing_id',
           'direction','start_time','end_time','start_price','end_price',
           'absolute_amplitude','pct_amplitude','atr_reference','amplitude_atr',
           'available_at','classification','reason_code','rule_version',
           'source_version','event_time','atr_multiplier','amplitude_threshold',
           'amplitude_filter_passed','duration_minutes','duration_bars',
           'config_hash','payload_json']


def make_leg(a, b, cfg, calendar):
    """Called only for validated consecutive, alternating swings."""
    start, end = Decimal(str(a['extreme_price'])), Decimal(str(b['extreme_price']))
    amplitude = abs(end-start)
    atr = a['atr_at_extreme']
    valid = atr is not None and pd.notna(atr) and math.isfinite(float(atr)) and float(atr)>0
    reference = Decimal(str(atr)) if valid else None
    threshold = reference*Decimal(str(cfg.atr_multiplier)) if valid else None
    passed = bool(amplitude >= threshold) if valid else None
    code = ('ATR_MISSING_OR_INVALID' if not valid else
            'AMPLITUDE_FILTER_PASSED' if passed else 'AMPLITUDE_TOO_SMALL_INTERNAL')
    minutes = (b['extreme_time']-a['extreme_time']).total_seconds()/60
    between = [x for x in calendar if a['extreme_time'] <= x <= b['extreme_time']]
    complete = (len(between)>1 and between[0]==a['extreme_time'] and between[-1]==b['extreme_time']
                and all(y-x==pd.Timedelta(minutes=15) for x,y in zip(between,between[1:])))
    key = [a['ticker'],a['timeframe'],a['source_version'],cfg.rule_version,cfg.config_hash,
           a['swing_id'],b['swing_id']]
    ident = hashlib.sha256(json.dumps(key,ensure_ascii=False).encode()).hexdigest()
    return dict(leg_id=ident,ticker=a['ticker'],timeframe=a['timeframe'],
        start_swing_id=a['swing_id'],end_swing_id=b['swing_id'],
        direction='UP' if a['swing_type']=='LOW' else 'DOWN',
        start_time=a['extreme_time'],end_time=b['extreme_time'],
        start_price=float(start),end_price=float(end),absolute_amplitude=float(amplitude),
        pct_amplitude=float(amplitude/start),atr_reference=float(reference) if valid else None,
        amplitude_atr=float(amplitude/reference) if valid else None,
        available_at=max(a['confirmed_at'],b['confirmed_at']),classification='UNCLASSIFIED',
        reason_code=code,rule_version=cfg.rule_version,source_version=a['source_version'],
        event_time=b['extreme_time'],atr_multiplier=cfg.atr_multiplier,
        amplitude_threshold=float(threshold) if valid else None,amplitude_filter_passed=passed,
        duration_minutes=minutes,duration_bars=len(between)-1 if complete else None,
        config_hash=cfg.config_hash,payload_json=json.dumps(dict(
            creation_reason='LEG_CREATED',rule_status='DRAFT',D04='PROPOSED',
            D05='PROPOSED_UNCHANGED',D09='APPROVED_QUARANTINE',D11='APPROVED_PROJECT_HYPOTHESIS',
            classification_note='Phase 2 does not evaluate structure rules; INTERNAL in reason code is SFS vocabulary only',
            percentage_unit='fraction',duration_bars_policy='NULL unless contiguous calendar; no inferred session bars'),sort_keys=True))


def build_legs(swings, ohlcv=None, *, as_of, config=None):
    cfg = config or LegConfig()
    lc = replace(cfg.labeling, rule_version=cfg.rule_version)
    cutoff = ts(as_of, lc)
    started = time.perf_counter()
    raw = swings.copy(deep=True).reset_index(drop=True)
    # Validate required schema and record malformed timestamps through Phase 1.
    final = build_labels(raw,ohlcv,as_of=cutoff,config=lc)
    events = {}
    if 'confirmed_at' in raw:
        for i,r in raw.iterrows():
            try:
                c=ts(r['confirmed_at'],lc)
            except (ValueError,TypeError,OverflowError):
                continue
            if c<=cutoff: events.setdefault(c,[]).append(i)
    calendar=[]
    if ohlcv is not None:
        for candle in ohlcv.to_dict('records'):
            try:
                d=ts(candle['Datetime'],lc)
                o,h,l,c,v=[float(candle[k]) for k in ['Open','High','Low','Close','Volume']]
                if not all(math.isfinite(z) for z in [o,h,l,c,v]) or min(o,h,l,c)<=0 or v<0 or h<max(o,l,c) or l>min(o,h,c):
                    continue
                if d+pd.Timedelta(minutes=15 if lc.candle_label=='open' else 0)<=cutoff:
                    calendar.append(d)
            except (ValueError,TypeError,OverflowError): pass
        calendar=sorted(set(calendar))
    accepted=[]; rejected=[]; emitted={}; replay_audit=[]
    for now,indices in sorted(events.items()):
        for i in indices:
            r=raw.iloc[i]
            try: e=ts(r['extreme_time'],lc)
            except (ValueError,TypeError,OverflowError,KeyError):
                accepted.append(i);continue
            collision=next((leg for leg in emitted.values() if leg['start_time']<e<leg['end_time']),None)
            # Identical technical duplicates must remain the Phase 1 dedup policy.
            if collision:
                rejected.append(i)
                replay_audit.append(dict(row_index=i,reason_code='DATA_ORDER_AMBIGUOUS',severity='QUARANTINE',
                    available_at=now,payload_json=json.dumps(dict(
                    issue='late swing would split a published leg',leg_id=collision['leg_id'],
                    action='quarantine new row; preserve published history; explicit versioned rebuild required'))))
            else: accepted.append(i)
        current=build_labels(raw.iloc[accepted],ohlcv,as_of=now,config=lc)
        ordered=current['sequence'].to_dict('records')
        for a,b in zip(ordered,ordered[1:]):
            leg=make_leg(a,b,cfg,calendar)
            # Only emit when the endpoint information is available in this batch.
            # A pair recovered after a quarantined sequence must not be backdated.
            if leg['available_at']<now and leg['leg_id'] not in emitted:
                replay_audit.append(dict(row_index=-1,reason_code='DATA_ORDER_AMBIGUOUS',severity='WARNING',
                    available_at=now,payload_json=json.dumps({'issue':'late recovered adjacency cannot be backdated','start':a['swing_id'],'end':b['swing_id']})))
                continue
            emitted.setdefault(leg['leg_id'],leg)
    legs=pd.DataFrame(emitted.values(),columns=COLUMNS)
    if not legs.empty:
        legs=legs.sort_values(['available_at','start_time','leg_id']).reset_index(drop=True)
    for col in ['atr_reference','amplitude_atr','amplitude_threshold','duration_bars']:
        legs[col]=pd.array(legs[col],dtype='Float64')
    legs['amplitude_filter_passed']=pd.array(legs['amplitude_filter_passed'],dtype='boolean')
    final['swing_leg']=legs
    final['phase2_audit']=pd.DataFrame(replay_audit,columns=['row_index','reason_code','severity','available_at','payload_json'])
    final['phase2_quarantine']=raw.iloc[rejected].copy()
    log=final['batch_log']
    log.update(legs=len(legs),phase2_quarantine=len(rejected),historical_legs_retained=True,
               atr_multiplier=cfg.atr_multiplier,rule_status='DRAFT',config_hash=cfg.config_hash,
               ticker=sorted(set(legs.ticker)) if len(legs) else [],timeframe='15m',
               source_version=sorted(set(legs.source_version)) if len(legs) else [],
               candidates=None,MAJOR=None,INTERNAL=None,UNCLASSIFIED=None,
               leg_UNCLASSIFIED=len(legs),later_phases='NOT_IMPLEMENTED',
               elapsed_ms=round((time.perf_counter()-started)*1000,3))
    final['leg_config']=asdict(cfg)
    return final


def sensitivity(legs, multipliers=(1.5,2.0,2.5,3.0)):
    """Pure re-evaluation of fixed leg geometry, not re-detection or selection."""
    records=[]
    for k in multipliers:
        if isinstance(k,bool) or not math.isfinite(k) or k<=0:raise ValueError('invalid multiplier')
        valid=legs.atr_reference.notna() & (legs.atr_reference>0)
        passes=sum(Decimal(str(a))>=Decimal(str(b))*Decimal(str(k))
                   for a,b in zip(legs.loc[valid,'absolute_amplitude'],legs.loc[valid,'atr_reference']))
        records.append(dict(atr_multiplier=k,legs=len(legs),valid_atr=int(valid.sum()),
            passed=int(passes),below_threshold=int(valid.sum())-int(passes),missing_atr=int((~valid).sum()),
            pass_rate=float(passes/valid.sum()) if valid.any() else None,
            classification='NOT_EVALUATED',rule_version=legs.rule_version.iloc[0] if len(legs) else None))
    return pd.DataFrame(records)

"""SFS Phase 1 only. Original Layer 2 is untouched. All policies are DRAFT.
A quarantined sequence is never silently compressed into a different price path.
OHLCV is accepted only to check candle availability, not to detect new swings.
"""
from dataclasses import dataclass,asdict
from decimal import Decimal
import math,json,time,logging
import pandas as pd

@dataclass(frozen=True)
class Config:
    rule_version: str='sfs-layer2-phase1-DRAFT-001'
    timezone: str='Asia/Ho_Chi_Minh'
    min_tick_tolerance: float=1.0
    equal_price_pct: float=.0001
    same_type_policy: str='QUARANTINE'
    tie_policy: str='QUARANTINE'
    pivot_right: int=3
    candle_label: str='open'
    def __post_init__(self):
        if not self.rule_version:raise ValueError('rule_version required')
        for x in (self.min_tick_tolerance,self.equal_price_pct):
            if not math.isfinite(x) or x<0:raise ValueError('Invalid tolerance')
        if self.same_type_policy!='QUARANTINE' or self.tie_policy!='QUARANTINE':raise ValueError('Replacement/tie policy not approved')
        if self.candle_label not in ('open','close') or not isinstance(self.pivot_right,int) or self.pivot_right<0:raise ValueError('Invalid confirmation contract')

COLS=['ticker','timeframe','swing_id','swing_type','extreme_time','confirmed_at','mechanical_label','reference_swing_id','price_difference','price_tolerance','rule_version','created_at','source_version','event_time','available_at','reason_code','payload_json']
REQUIRED=['swing_id','ticker','timeframe','swing_type','extreme_price','extreme_time','confirmed_at','atr_at_extreme']

def ts(x,cfg):
    if x is None or isinstance(x,(int,float,bool)) or pd.isna(x):raise ValueError('Invalid timestamp')
    t=pd.Timestamp(x)
    if pd.isna(t):raise ValueError('NaT')
    return t.tz_localize(cfg.timezone) if t.tzinfo is None else t.tz_convert(cfg.timezone)

def build_labels(swings,ohlcv=None,*,as_of,config=None):
    cfg=config or Config();cutoff=ts(as_of,cfg);start=time.perf_counter()
    raw=swings.copy(deep=True);audit=[];rows=[];blocked=set();future=0
    def note(i,reason,severity='QUARANTINE',**payload):
        audit.append(dict(row_index=i,reason_code=reason,severity=severity,payload_json=json.dumps(payload,default=str,ensure_ascii=False)))
        if severity=='QUARANTINE':blocked.add(i)
    schema=set(REQUIRED)-set(raw.columns)
    if not ('source_version' in raw or 'rule_version' in raw):schema.add('source_version/rule_version')
    if schema:
        for i in range(len(raw)):note(i,'INVALID_SWING_SEQUENCE',missing_columns=sorted(schema))
        if raw.empty:note(-1,'INVALID_SWING_SEQUENCE',missing_columns=sorted(schema))
    else:
        for i,r in enumerate(raw.to_dict('records')):
            try:c=ts(r['confirmed_at'],cfg)
            except (ValueError,TypeError,OverflowError):note(i,'INVALID_TIMESTAMP',field='confirmed_at');continue
            if c>cutoff:future+=1;continue
            sid=r['swing_id']
            if pd.isna(sid) or isinstance(sid,bool) or not str(sid).strip():note(i,'INVALID_SWING_ID');continue
            if isinstance(sid,float):
                if not math.isfinite(sid) or not sid.is_integer():note(i,'INVALID_SWING_ID');continue
                sid=int(sid)
            r['swing_id']=str(sid).strip()
            if r['swing_type'] not in ('HIGH','LOW'):note(i,'INVALID_SWING_TYPE');continue
            try:p=float(r['extreme_price'])
            except (TypeError,ValueError):p=float('nan')
            if isinstance(r['extreme_price'],bool) or not math.isfinite(p) or p<=0:note(i,'INVALID_PRICE');continue
            try:
                e=ts(r['extreme_time'],cfg)
                minimum=pd.Timedelta(minutes=15*(cfg.pivot_right+(cfg.candle_label=='open')))
                if c<e+minimum:raise ValueError('Confirmation too early')
                for key,value in [('extreme_time',e),('confirmed_at',c)]:
                    if key+'_iso' in r and pd.notna(r[key+'_iso']) and ts(r[key+'_iso'],cfg)!=value:raise ValueError('ISO alias disagrees')
            except (TypeError,ValueError,OverflowError):note(i,'INVALID_TIMESTAMP',field='extreme_time/confirmation/ISO');continue
            if pd.isna(r['ticker']) or not str(r['ticker']).strip() or r['timeframe']!='15m':note(i,'INVALID_SWING_SEQUENCE',field='ticker/timeframe');continue
            source=r.get('source_version',r.get('rule_version'))
            if pd.isna(source) or not str(source).strip():note(i,'SOURCE_VERSION_CHANGED',issue='missing_version');continue
            try:a=float(r['atr_at_extreme'])
            except (ValueError,TypeError):a=float('nan')
            if not math.isfinite(a) or a<=0:
                a=None;note(i,'ATR_MISSING_OR_INVALID','WARNING',action='NULL; geometry only; no amplitude calculation')
            rows.append({**r,'ticker':str(r['ticker']).strip().upper(),'source_version':str(source),'extreme_time':e,'confirmed_at':c,'extreme_price':p,'atr_at_extreme':a,'_row':i})
    if rows and (len({r['ticker'] for r in rows})>1 or len({r['source_version'] for r in rows})>1):
        code='SOURCE_VERSION_CHANGED' if len({r['source_version'] for r in rows})>1 else 'INVALID_SWING_SEQUENCE'
        for r in rows:note(r['_row'],code,issue='mixed batch')
        rows=[]
    groups={}
    for r in rows:groups.setdefault(r['swing_id'],[]).append(r)
    rows=[]
    for group in groups.values():
        signatures={json.dumps({k:v for k,v in r.items() if k!='_row'},sort_keys=True,default=str) for r in group}
        if len(signatures)>1:
            for r in group:note(r['_row'],'DUPLICATE_SWING',issue='conflicting payload; no winner')
        else:
            rows.append(group[0])
            for r in group[1:]:note(r['_row'],'DUPLICATE_SWING','DEDUPLICATED',kept_row=group[0]['_row'])
    check='MINIMUM_ELAPSED_BOUND_ONLY'
    if ohlcv is not None:
        needed={'Datetime','Open','High','Low','Close','Volume'}
        if not needed.issubset(ohlcv):raise ValueError('OHLCV schema missing')
        calendar=[]
        for candle in ohlcv.to_dict('records'):
            try:
                d=ts(candle['Datetime'],cfg);closed=d+pd.Timedelta(minutes=15 if cfg.candle_label=='open' else 0)
                if closed>cutoff:continue
                o,h,l,c,v=[float(candle[k]) for k in ['Open','High','Low','Close','Volume']]
                if not all(math.isfinite(x) for x in [o,h,l,c,v]) or min(o,h,l,c)<=0 or v<0 or h<max(o,l,c) or l>min(o,h,c):raise ValueError()
                calendar.append(d)
            except (ValueError,TypeError):note(-1,'INVALID_PRICE','WARNING',table='OHLCV',issue='invalid candle excluded')
        calendar=sorted(set(calendar));positions={d:i for i,d in enumerate(calendar)};good=[]
        for r in rows:
            i=positions.get(r['extreme_time']);j=None if i is None else i+cfg.pivot_right
            if j is None or j>=len(calendar) or calendar[j]+pd.Timedelta(minutes=15 if cfg.candle_label=='open' else 0)>r['confirmed_at']:
                note(r['_row'],'INVALID_TIMESTAMP',issue='missing right window or premature confirmation')
            else:good.append(r)
        rows=good;check='CLOSED_OHLCV_RIGHT_WINDOW'
    ordered=sorted(rows,key=lambda r:r['extreme_time'])
    issue=None
    if any(a['extreme_time']==b['extreme_time'] for a,b in zip(ordered,ordered[1:])):issue='DATA_ORDER_AMBIGUOUS'
    elif any(a['swing_type']==b['swing_type'] for a,b in zip(ordered,ordered[1:])):issue='INVALID_SWING_SEQUENCE'
    if issue:
        for r in ordered:note(r['_row'],issue,action='entire eligible sequence blocked; original records retained')
        ordered=[]
    labels=[];prior={};watermark=None;created=pd.Timestamp.now(tz='UTC').isoformat()
    for r in ordered:
        kind=r['swing_type'];ref=prior.get(kind);p=Decimal(str(r['extreme_price']))
        tolerance=max(Decimal(str(cfg.min_tick_tolerance)),p*Decimal(str(cfg.equal_price_pct)))
        diff=None if ref is None else p-Decimal(str(ref['extreme_price']))
        if ref is None:label='FIRST_'+kind
        elif abs(diff)<=tolerance:label='EQH' if kind=='HIGH' else 'EQL'
        elif diff>0:label='HH' if kind=='HIGH' else 'HL'
        else:label='LH' if kind=='HIGH' else 'LL'
        watermark=r['confirmed_at'] if watermark is None else max(watermark,r['confirmed_at'])
        labels.append(dict(ticker=r['ticker'],timeframe=r['timeframe'],swing_id=r['swing_id'],swing_type=kind,extreme_time=r['extreme_time'],confirmed_at=r['confirmed_at'],mechanical_label=label,reference_swing_id=None if ref is None else ref['swing_id'],price_difference=None if diff is None else float(diff),price_tolerance=float(tolerance),rule_version=cfg.rule_version,created_at=created,source_version=r['source_version'],event_time=r['extreme_time'],available_at=watermark,reason_code=label if ref is None else 'LABEL_'+label,payload_json=json.dumps({'policy_status':'PROPOSED','rule_status':'DRAFT'})))
        prior[kind]=r
    q=[]
    for i in sorted(blocked):
        if i>=0:q.append({'row_index':i,'raw_json':raw.iloc[[i]].to_json(orient='records',date_format='iso'),'reason_code':next(a['reason_code'] for a in audit if a['row_index']==i and a['severity']=='QUARANTINE')})
    log=dict(rule_version=cfg.rule_version,as_of=str(cutoff),input_swings=len(raw),valid_swings=len(rows),quarantine=len(q),labels=len(labels),future_excluded=future,confirmation_check=check,elapsed_ms=round((time.perf_counter()-start)*1000,3),later_phases='NOT_IMPLEMENTED',legs=None,MAJOR=None,INTERNAL=None,UNCLASSIFIED=None,CONFIRMED=None,BROKEN=None,UNCLEAR=None)
    logging.getLogger(__name__).info('phase1_batch %s',log)
    return {'raw':raw,'validated':pd.DataFrame(rows),'sequence':pd.DataFrame(ordered),'swing_label':pd.DataFrame(labels,columns=COLS),'audit':pd.DataFrame(audit,columns=['row_index','reason_code','severity','payload_json']),'quarantine':pd.DataFrame(q,columns=['row_index','raw_json','reason_code']),'batch_log':log,'config':asdict(cfg)}

"""Causal cleaning and exact Wilder ATR. Missing candles are never fabricated."""
import logging
import numpy as np
import pandas as pd
from .config import SwingDetectorConfig
LOG=logging.getLogger(__name__)
ALIASES={'Datetime':('Datetime','TRADE_DATE','trade_date','datetime','Date','date'),
         'Open':('Open','OPEN_PRICE','open'),'High':('High','HIGH_PRICE','high'),
         'Low':('Low','LOW_PRICE','low'),'Close':('Close','CLOSE_PRICE','close'),
         'Volume':('Volume','VOLUME','volume')}

def normalize_columns(df):
    data=df.copy()
    if isinstance(data.index,pd.DatetimeIndex) and not any(c in data for c in ALIASES['Datetime']):
        data['Datetime']=data.index
    for target, aliases in ALIASES.items():
        if target not in data:
            source=next((c for c in aliases if c in data),None)
            if source is None: raise ValueError('Missing required column: '+target)
            data[target]=data[source]
    return data.reset_index(drop=True)

def local_time(value,cfg):
    t=pd.Timestamp(value)
    if pd.isna(t): raise ValueError('Missing timestamp')
    return t.tz_localize(cfg.naive_timezone) if t.tzinfo is None else t.tz_convert(cfg.timezone)

def clean_data(df,config=None,as_of=None,expected_timestamps=None):
    """First VALID record per timestamp wins. Naive timestamps mean config.naive_timezone.
    Session template is not an exchange calendar; missing template slots are warnings only.
    With open labels a bar becomes available 15 minutes after its label.
    """
    cfg=config or SwingDetectorConfig(); data=normalize_columns(df)
    reasons=[]; kept=[]; cutoff=local_time(as_of,cfg) if as_of is not None else None
    shift=pd.Timedelta(minutes=15) if cfg.timestamp_label=='open' else pd.Timedelta(0)
    for i,row in data.iterrows():
        reason=None
        try: dt=local_time(row.Datetime,cfg).tz_convert(cfg.timezone)
        except (ValueError,TypeError,OverflowError):
            reasons.append({'source_row':int(i),'reason':'invalid_datetime'});continue
        if cutoff is not None and dt+shift>cutoff: continue
        vals=pd.to_numeric(row[['Open','High','Low','Close','Volume']],errors='coerce').to_numpy(dtype=float)
        if not np.isfinite(vals).all(): reason='missing_or_nonfinite'
        else:
            o,h,l,c,v=vals
            if min(o,h,l,c)<=0: reason='nonpositive_price'
            elif h<max(o,c,l) or l>min(o,c,h): reason='invalid_ohlc'
            elif v<0: reason='negative_volume'
        if reason is None and (dt.minute%15 or dt.second or dt.microsecond or dt.nanosecond): reason='off_15m_grid'
        minute=dt.hour*60+dt.minute
        def minutes(s):
            h,m=map(int,s.split(':'));return h*60+m
        in_session=any((minutes(a)<=minute<minutes(b)) if cfg.timestamp_label=='open'
                       else (minutes(a)<minute<=minutes(b)) for a,b in cfg.sessions)
        if reason is None and (dt.weekday()>4 or not in_session): reason='outside_session'
        if reason:
            reasons.append({'source_row':int(i),'time':str(dt),'reason':reason});continue
        kept.append(dict(Datetime=dt,Open=vals[0],High=vals[1],Low=vals[2],Close=vals[3],Volume=vals[4],source_row=i))
    out=pd.DataFrame(kept,columns=['Datetime','Open','High','Low','Close','Volume','source_row'])
    if len(out):
        out=out.sort_values('Datetime',kind='stable')
        duplicate=out.Datetime.duplicated(keep='first')
        for _,r in out[duplicate].iterrows(): reasons.append({'source_row':int(r.source_row),'time':str(r.Datetime),'reason':'duplicate_datetime'})
        out=out[~duplicate].reset_index(drop=True)
    out['available_time']=out.Datetime+shift if len(out) else pd.Series(dtype=f'datetime64[ns, {cfg.timezone}]')
    missing=[]
    if len(out):
        if expected_timestamps is not None:
            expected=pd.DatetimeIndex([local_time(x,cfg) for x in expected_timestamps]);calendar='provided'
        else:
            expected=[];calendar='weekday_session_template_not_exchange_calendar'
            for day in pd.date_range(out.Datetime.iloc[0].normalize(),out.Datetime.iloc[-1].normalize(),freq='B'):
                for a,b in cfg.sessions:
                    times=pd.date_range(str(day.date())+' '+a,str(day.date())+' '+b,freq='15min',tz=cfg.timezone)
                    expected.extend(times[:-1] if cfg.timestamp_label=='open' else times[1:])
            expected=pd.DatetimeIndex(expected)
        expected=expected[(expected>=out.Datetime.iloc[0])&(expected<=out.Datetime.iloc[-1])]
        missing=[str(t) for t in expected.difference(pd.DatetimeIndex(out.Datetime))]
    else: calendar='not_evaluated'
    counts=pd.Series([r['reason'] for r in reasons],dtype=object).value_counts().to_dict()
    diagnostics={'input_rows':len(df),'clean_rows':len(out),'removed_rows':len(reasons),'removal_counts':counts,
                 'removed':reasons,'zero_volume_rows':int((out.Volume==0).sum()),'calendar':calendar,
                 'potential_missing_bars':len(missing),'missing_timestamps':missing,'timestamp_label':cfg.timestamp_label}
    if counts: LOG.warning('Removed %s candles: %s',len(reasons),counts)
    if missing: LOG.warning('%s potential missing 15m slots (%s)',len(missing),calendar)
    out.attrs['diagnostics']=diagnostics
    return out,diagnostics

def validate_and_clean_data(df,config=None):
    return clean_data(df,config)[0]

def compute_wilder_atr(df,period=14):
    """First TR=H-L. First period-1 ATRs are NaN; no warmup partial mean."""
    if not isinstance(period,int) or period<1: raise ValueError('period must be positive integer')
    cols={k:next((c for c in ALIASES[k] if c in df),None) for k in ['High','Low','Close']}
    if not all(cols.values()): raise ValueError('High, Low, Close required')
    n=len(df); atr=np.full(n,np.nan)
    if not n: return atr
    h,l,c=(df[cols[k]].to_numpy(dtype=float) for k in ['High','Low','Close'])
    if not np.isfinite(np.concatenate([h,l,c])).all(): raise ValueError('Clean missing/nonfinite prices before ATR')
    tr=h-l
    tr[1:]=np.maximum.reduce([tr[1:],np.abs(h[1:]-c[:-1]),np.abs(l[1:]-c[:-1])])
    if n>=period:
        atr[period-1]=tr[:period].mean()
        for i in range(period,n): atr[i]=((period-1)*atr[i-1]+tr[i])/period
    return atr

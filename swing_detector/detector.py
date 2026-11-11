"""Independent causal Layer 1. No Layer 2 or database dependency.

Candidate extrema must satisfy the left window. Equal prices in that window
reject a later candidate (first tie); right window allows equality. Only a
complete right window makes a pivot eligible. Frozen threshold uses ATR at the
extreme candle, not at pivot discovery. Reversal must still be present on the
confirmation candle; earlier touches are not replayed/backdated.

An outside bar that spans the active threshold is ambiguous: defer confirmation
on that bar. INIT with both directions eligible also defers. At most one swing
per bar. Opposite seeds may be selected from already observed bars after the
last extreme, but confirmation can only happen on a later processing step.
"""
from dataclasses import dataclass
import logging
import numpy as np
import pandas as pd
from .config import SwingDetectorConfig
from .atr import clean_data,compute_wilder_atr
LOG=logging.getLogger(__name__)
SOURCE_VERSION='qta-layer1-1.1.0'
RULE_VERSION='wilder-pivot-zigzag-v1'
COLUMNS=['swing_id','ticker','timeframe','swing_type','extreme_price','extreme_time','confirmed_at',
         'atr_at_extreme','source_version','rule_version','threshold_T',
         'reversal_size_in_ATR','bars_since_prev_swing','confirm_delay_bars','volume_ratio','label']

@dataclass
class DetectionResult:
    swings: pd.DataFrame
    candles: pd.DataFrame
    diagnostics: dict
    events: list
    indices: list

def left_qualified(values,i,left,kind):
    if i<left:return False
    prior=values[i-left:i]
    return bool(values[i]>np.max(prior) if kind=='HIGH' else values[i]<np.min(prior))

def pivot_qualified(values,i,t,left,right,kind):
    if t<i+right or not left_qualified(values,i,left,kind):return False
    following=values[i+1:i+right+1]
    return bool(values[i]>=np.max(following) if kind=='HIGH' else values[i]<=np.min(following))

def detect_result(ohlcv_15m,config=None,*,as_of=None,expected_timestamps=None):
    cfg=config or SwingDetectorConfig()
    df,diag=clean_data(ohlcv_15m,cfg,as_of,expected_timestamps)
    atr=compute_wilder_atr(df,cfg.atr_period);df['ATR']=atr
    values={'HIGH':df.High.to_numpy(float),'LOW':df.Low.to_numpy(float)}
    vol=df.Volume.to_numpy(float); cumulative=np.r_[0.,np.cumsum(vol)]
    median=pd.Series(vol).shift(1).rolling(cfg.volume_lookback,min_periods=cfg.volume_lookback).median().to_numpy()
    candidates={'HIGH':None,'LOW':None};state='INIT';rows=[];events=[];indices=[];prior_same={};previous=None
    def event(t,reason,**kw):events.append(dict(bar=int(t),time=str(df.Datetime.iloc[t]),reason=reason,**kw))
    def new_candidate(kind,i,t):
        p=values[kind][i];candidate=(i,float(p),float(atr[i]),float(max(cfg.reversal_atr_mult*atr[i],cfg.reversal_min_pct*p)))
        event(t,'candidate',type=kind,extreme_index=int(i),threshold_T=candidate[3]);return candidate
    def update(kind,t):
        if not np.isfinite(atr[t]):return
        c=candidates[kind];v=values[kind][t]
        better=c is None or (v>c[1] if kind=='HIGH' else v<c[1])
        if better:
            if left_qualified(values[kind],t,cfg.pivot_left,kind):candidates[kind]=new_candidate(kind,t,t)
            else:event(t,'rejected_left_or_first_tie',type=kind,price=float(v))
    for t in range(len(df)):
        active=('HIGH','LOW') if state=='INIT' else (state,)
        for kind in active:update(kind,t)
        ready=[]; ambiguous=False
        for kind in active:
            c=candidates[kind]
            if c is None:continue
            i,p,a,threshold=c
            reversal=p-values['LOW'][t] if kind=='HIGH' else values['HIGH'][t]-p
            # Broad, conservative outside-bar rule avoids inventing intrabar order.
            outside=(t>0 and values['HIGH'][t]>values['HIGH'][t-1] and values['LOW'][t]<values['LOW'][t-1])
            if outside and values['HIGH'][t]-values['LOW'][t]>=threshold and (i==t or reversal>=threshold):
                ambiguous=True
            if pivot_qualified(values[kind],i,t,cfg.pivot_left,cfg.pivot_right,kind) and reversal>=threshold:
                if previous is not None and i-previous<cfg.min_bars_between_swings:
                    event(t,'min_spacing',type=kind,extreme_index=i);continue
                ready.append((kind,c,float(reversal)))
        event(t,'state',state=state,candidates={kind: {'index':c[0],'price':c[1],'threshold_T':c[3],
                'reversal':float(c[1]-values['LOW'][t] if kind=='HIGH' else values['HIGH'][t]-c[1]),
                'pivot_ready':pivot_qualified(values[kind],c[0],t,cfg.pivot_left,cfg.pivot_right,kind)}
                for kind,c in candidates.items() if c is not None})
        if ambiguous or len(ready)>1:
            event(t,'ambiguous_defer',state=state,eligible=[r[0] for r in ready]);continue
        if not ready:continue
        kind,(i,p,a,threshold),reversal=ready[0]
        last=prior_same.get(kind)
        label=None if last is None or p==last else (('HH' if p>last else 'LH') if kind=='HIGH' else ('HL' if p>last else 'LL'))
        volume_ratio=(cumulative[t+1]-cumulative[i+1])/median[i] if np.isfinite(median[i]) and median[i]>0 else np.nan
        rows.append(dict(swing_id=len(rows)+1,ticker=cfg.ticker,timeframe=cfg.timeframe,
                         swing_type=kind,extreme_price=p,extreme_time=df.Datetime.iloc[i],
                         source_version=SOURCE_VERSION,rule_version=RULE_VERSION,
                         confirmed_at=df.available_time.iloc[t],atr_at_extreme=a,threshold_T=threshold,
                         reversal_size_in_ATR=reversal/a if a>0 else np.nan,
                         bars_since_prev_swing=i-previous if previous is not None else np.nan,
                         confirm_delay_bars=t-i,volume_ratio=volume_ratio,label=label))
        indices.append((int(i),int(t)));prior_same[kind]=p;previous=i
        event(t,'confirmed',type=kind,extreme_index=i,threshold_T=threshold)
        state='LOW' if kind=='HIGH' else 'HIGH';candidates={'HIGH':None,'LOW':None}
        # Seed from known bars, strictly after the previous extreme; no future data.
        for j in range(i+1,t+1):
            if not np.isfinite(atr[j]) or not left_qualified(values[state],j,cfg.pivot_left,state):continue
            c=candidates[state]
            if c is None or (values[state][j]>c[1] if state=='HIGH' else values[state][j]<c[1]):
                candidates[state]=new_candidate(state,j,t)
    result=pd.DataFrame(rows,columns=COLUMNS)
    diag['ambiguous_deferred_bars']=sum(e['reason']=='ambiguous_defer' for e in events)
    diag['confirmed_swings']=len(rows)
    if diag['ambiguous_deferred_bars']:LOG.info('Ambiguous bars deferred: %s',diag['ambiguous_deferred_bars'])
    result.attrs['diagnostics']=diag
    return DetectionResult(result,df,diag,events,indices)

def detect_swings_frame(ohlcv_15m,config=None,**kwargs):
    return detect_result(ohlcv_15m,config,**kwargs).swings

class SwingList(list):
    """Legacy list interface carrying canonical output for the Layer 1 exporter."""
    pass

def detect_swings(ohlcv_15m,config=None):
    """Backward compatible List[common.models.Swing] adapter; core stays independent."""
    from common.models import Swing
    result=detect_result(ohlcv_15m,config);output=SwingList()
    output.layer1_result=result
    for r,(i,t) in zip(result.swings.to_dict('records'),result.indices):
        pct=(r['extreme_price']/output[-1].extreme_price-1)*100 if output else None
        output.append(Swing(swing_id=r['swing_id'],swing_type=r['swing_type'],extreme_price=r['extreme_price'],
            extreme_time=r['extreme_time'].strftime('%Y-%m-%d %H:%M:%S'),
            confirmed_at=r['confirmed_at'].strftime('%Y-%m-%d %H:%M:%S'),
            atr_at_extreme=r['atr_at_extreme'],threshold=r['threshold_T'],lag_bars=r['confirm_delay_bars'],
            vol_over_median=r['volume_ratio'],pct_change=pct,index=i,confirmed_at_index=t,structure_label=None))
    return output

"""Causal features; confirmed pivots are emitted on confirmation day, never backdated."""
import numpy as np
import pandas as pd
from src.research import indicators,wilder
FEATURES=['return20','ma_gap','slope50','adx','atr_fraction','volume_ratio','obv_flow','ad_flow','rsi14','macd_scaled','contraction','breakout']
WEIGHTS={'UPTREND':(.45,.2,.2,.15),'DOWNTREND':(.2,.15,.25,.4),'SIDEWAYS':(.15,.3,.25,.3),'HIGH_VOL':(.2,.15,.35,.3)}

def features(f):
    i=indicators(f);c=f.CLOSE_PRICE.astype(float);h=f.HIGH_PRICE.astype(float);l=f.LOW_PRICE.astype(float);v=f.VOLUME.astype(float)
    up=h.diff();down=-l.diff();plus=up.where((up>down)&(up>0),0);minus=down.where((down>up)&(down>0),0)
    pdm=wilder(plus)/i.atr14.replace(0,np.nan);mdm=wilder(minus)/i.atr14.replace(0,np.nan)
    dx=(100*(pdm-mdm).abs()/(pdm+mdm).replace(0,np.nan)).fillna(0)
    i['adx']=wilder(dx);i['slope50']=i.ma50/i.ma50.shift(5)-1;i['atr_fraction']=i.atr14/c
    i['atr_percentile']=i.atr_fraction.rolling(252,min_periods=60).rank(pct=True)*100
    i['regime']=np.select([i.atr_percentile>=90,(i.adx>=25)&(i.slope50>.002),(i.adx>=25)&(i.slope50<-.002)],['HIGH_VOL','UPTREND','DOWNTREND'],default='SIDEWAYS')
    i.loc[i.ma50.isna()|i.atr_percentile.isna(),'regime']='INSUFFICIENT'
    signed=np.sign(c.diff()).fillna(0)*v;i['obv']=signed.cumsum()
    mf=((2*c-h-l)/(h-l).replace(0,np.nan)).fillna(0)*v;i['ad']=mf.cumsum();den=v.rolling(20).sum().replace(0,np.nan)
    i['obv_flow']=signed.rolling(20).sum()/den;i['ad_flow']=mf.rolling(20).sum()/den
    i['dry_up']=v.rolling(5).mean()<v.shift(5).rolling(20).mean()*.6
    width=(h.rolling(10).max()-l.rolling(10).min())/c
    i['contraction']=((width<width.shift(10))&(width.shift(10)<width.shift(20))).astype(int)
    ph=h.shift(3).eq(h.rolling(7).max());pl=l.shift(3).eq(l.rolling(7).min())
    i['swing_high_confirmed']=ph;i['swing_low_confirmed']=pl;i['resistance']=h.shift(3).where(ph).ffill();i['support']=l.shift(3).where(pl).ffill()
    i['breakout']=((c>i.resistance.shift())&(c.shift()<=i.resistance.shift())&(i.volume_ratio>=1.5)).astype(int)
    i['pullback']=(c>i.ma50)&(l<=i.ma20)&(c>=i.ma20)
    for key in ['rsi14','macd_hist']:
        hip=i[key].shift(3).where(ph);lop=i[key].shift(3).where(pl)
        i[key+'_bear_div']=ph&(h.shift(3)>i.resistance.shift())&(hip<hip.ffill().shift())
        i[key+'_bull_div']=pl&(l.shift(3)<i.support.shift())&(lop>lop.ffill().shift())
    i['return20']=c.pct_change(20,fill_method=None);i['ma_gap']=c/i.ma50-1;i['macd_scaled']=i.macd_hist/c
    parts=pd.DataFrame({'trend':((c>i.ma20).astype(int)+(i.ma20>i.ma50).astype(int)+(c>i.ma200).astype(int))/3,
        'momentum':(i.rsi14.between(50,70).astype(int)+(i.macd_hist>0).astype(int))/2,
        'flow':((i.obv_flow>0).astype(int)+(i.ad_flow>0).astype(int))/2,
        'setup':(i.breakout+i.pullback.astype(int)+i.contraction)/3},index=i.index)
    i['adaptive_score']=0.
    for regime,weights in WEIGHTS.items():
        mask=i.regime.eq(regime);i.loc[mask,'adaptive_score']=parts.loc[mask].mul(weights,axis=1).sum(axis=1)*100
    i.loc[i.regime.eq('INSUFFICIENT'),'adaptive_score']=np.nan
    for col in parts:i['component_'+col]=parts[col]*100
    return i.replace([np.inf,-np.inf],np.nan)

def weekly(f,today=None):
    today=pd.Timestamp(today or pd.Timestamp.now(tz='Asia/Ho_Chi_Minh').date()).normalize()
    end=today if today.weekday()>=5 else today-pd.Timedelta(days=today.weekday())
    x=f.loc[pd.to_datetime(f.TRADE_DATE)<end].copy().set_index('TRADE_DATE')
    return x.resample('W-FRI').agg({'OPEN_PRICE':'first','HIGH_PRICE':'max','LOW_PRICE':'min','CLOSE_PRICE':'last','VOLUME':'sum'}).dropna().reset_index()

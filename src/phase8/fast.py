"""Latest-bar vector calculations, versioned per-symbol persistent cache."""
import os,time,json,hashlib,sqlite3
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.signal import lfilter
from src.phase7.data import safe
from src.discovery import db_revision
from src.phase7.features import WEIGHTS
from src.phase8.data import connect,read,members
VERSION='8.0.1';_hot={}
def smooth(a,n=14,ema=False):
    a=np.asarray(a,float);out=np.full(len(a),np.nan)
    start=0 if ema else n-1
    if len(a)<=start:return out
    alpha=2/(n+1) if ema else 1/n;seed=a[0] if ema else a[:n].mean();out[start]=seed
    if len(a)>start+1:out[start+1:]=lfilter([alpha],[1,-(1-alpha)],a[start+1:],zi=[seed*(1-alpha)])[0]
    return out
def ma(a,n):
    out=np.full(len(a),np.nan)
    if len(a)>=n:out[n-1:]=np.convolve(a,np.ones(n)/n,mode='valid')
    return out
def latest(a):
    o,h,l,c,v=a.T;n=len(c)
    if n<60:return {'status':'INSUFFICIENT','score':None}
    if not np.isfinite(a).all() or (a[:,:4]<=0).any() or (v<0).any() or (h<np.maximum(o,c)).any() or (l>np.minimum(o,c)).any() or (h<l).any():return {'status':'INVALID','score':None}
    m20=ma(c,20);m50=ma(c,50);m200=ma(c,200);diff=np.diff(c)
    gain=smooth(np.maximum(diff,0))[-1];loss=smooth(np.maximum(-diff,0))[-1];rsi=100-100/(1+gain/loss) if loss else (100 if gain else 50)
    macd=smooth(c,12,True)-smooth(c,26,True);sig=smooth(macd[25:],9,True);hist=macd[-1]-sig[-1]
    prev=np.r_[c[0],c[:-1]];atr=smooth(np.maximum.reduce([h-l,abs(h-prev),abs(l-prev)]));atrfrac=atr/c
    up=np.r_[0,np.diff(h)];dn=np.r_[0,-np.diff(l)];plus=smooth(np.where((up>dn)&(up>0),up,0));minus=smooth(np.where((dn>up)&(dn>0),dn,0))
    den=plus+minus;dx=np.divide(100*abs(plus-minus),den,out=np.zeros(n),where=np.isfinite(den)&(den>0));adx=smooth(dx)[-1]
    recent=atrfrac[-252:];recent=recent[np.isfinite(recent)];percent=(np.sum(recent<atrfrac[-1])+(np.sum(recent==atrfrac[-1])+1)/2)/len(recent)*100
    slope=m50[-1]/m50[-6]-1
    regime='HIGH_VOL' if percent>=90 else ('UPTREND' if adx>=25 and slope>.002 else ('DOWNTREND' if adx>=25 and slope<-.002 else 'SIDEWAYS'))
    if len(recent)<60:regime='INSUFFICIENT'
    sumv=v[-20:].sum();obv=np.sum(np.sign(np.r_[0,diff])[-20:]*v[-20:])/sumv if sumv else 0
    money=np.divide(2*c-h-l,h-l,out=np.zeros(n),where=h>l)*v;ad=money[-20:].sum()/sumv if sumv else 0
    # Floating noise at flat midpoint must not award flow points.
    obv=0 if abs(obv)<1e-10 else obv;ad=0 if abs(ad)<1e-10 else ad
    resist=np.full(n,np.nan);support=np.full(n,np.nan)
    from numpy.lib.stride_tricks import sliding_window_view
    wh=sliding_window_view(h,7);wl=sliding_window_view(l,7);hi=np.flatnonzero(h[3:-3]==wh.max(axis=1))+6;lo=np.flatnonzero(l[3:-3]==wl.min(axis=1))+6
    resistance=h[hi[-1]-3] if len(hi) else np.nan;prior_hi=hi[hi<n-1];pr=h[prior_hi[-1]-3] if len(prior_hi) else np.nan
    support=l[lo[-1]-3] if len(lo) else np.nan
    vr=v[-1]/v[-21:-1].mean() if v[-21:-1].mean() else np.nan
    breakout=int(c[-1]>pr and c[-2]<=pr and vr>=1.5);pullback=int(c[-1]>m50[-1] and l[-1]<=m20[-1] and c[-1]>=m20[-1])
    widths=[(h[n-j-10:n-j].max()-l[n-j-10:n-j].min())/c[n-j-1] for j in [0,10,20]];contraction=int(widths[0]<widths[1]<widths[2])
    parts=[sum([c[-1]>m20[-1],m20[-1]>m50[-1],c[-1]>m200[-1]])/3,(int(50<=rsi<=70)+int(hist>0))/2,(int(obv>0)+int(ad>0))/2,(breakout+pullback+contraction)/3]
    contributions=dict(zip(['trend','momentum','flow','setup'],[p*w*100 for p,w in zip(parts,WEIGHTS.get(regime,[0]*4))]))
    return safe({'status':'UNVERIFIED','score':sum(contributions.values()) if regime!='INSUFFICIENT' else None,'regime':regime,'close':c[-1],'ma50':m50[-1],'ma200':m200[-1],'rsi':rsi,'adx':adx,'atr':atr[-1],'return20':c[-1]/c[-21]-1,'volume_ratio':vr,'obv_flow':obv,'ad_flow':ad,'support':support,'resistance':resistance,'why':contributions,'price_basis':'LEGACY_UNKNOWN','evidence':'Chưa đủ bằng chứng','probability':None})
def scan(path,cache=None):
    started=time.perf_counter();p=Path(path);stat=p.stat();rev=db_revision(path);key=(rev,VERSION,pd.Timestamp.now(tz='Asia/Ho_Chi_Minh').strftime('%Y-%m-%d'))
    if rev and cache is None and _hot.get('key')==key:return {**_hot['value'],'seconds':time.perf_counter()-started,'cache':'memory','computed':0}
    cache=cache or os.getenv('QTA8_CACHE',str(p.parent/'qta8_cache.db'));Path(cache).parent.mkdir(parents=True,exist_ok=True)
    with connect(path,True) as db:
        rows=db.execute('SELECT SYMBOL,TRADE_DATE,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,CLOSE_PRICE,VOLUME FROM STOCK_PRICES WHERE TRADE_DATE<? ORDER BY SYMBOL,TRADE_DATE',(key[-1],)).fetchall()
    groups={}
    for row in rows:groups.setdefault(row[0],[]).append(row[1:])
    raw=read(path,'prices');universe=read(path,'universe');bench=read(path,'benchmarks');asof=key[-1]
    for s,g in raw.loc[raw.date<asof].groupby('symbol'):groups[s]=list(g.sort_values('date')[['date','open','high','low','close','volume']].itertuples(index=False,name=None))
    items=[];computed=0
    with sqlite3.connect(cache) as db:
        db.execute('CREATE TABLE IF NOT EXISTS features(symbol TEXT PRIMARY KEY,version TEXT,digest TEXT,payload TEXT)')
        old={r[0]:r[1:] for r in db.execute('SELECT * FROM features')}
        for s,values in groups.items():
            dates=[str(r[0])[:10] for r in values];a=np.array([r[1:] for r in values],dtype=float);digest=hashlib.sha256(a.tobytes()+','.join(dates).encode()).hexdigest();saved=old.get(s)
            if saved and saved[0]==VERSION and saved[1]==digest:r=json.loads(saved[2])
            else:
                r=latest(a);computed+=1;db.execute('INSERT OR REPLACE INTO features VALUES(?,?,?,?)',(s,VERSION,digest,json.dumps(r,allow_nan=False)))
            r={**r,'symbol':s,'as_of':dates[-1],'bars':len(values),'age_days':(pd.Timestamp(asof)-pd.Timestamp(dates[-1])).days,'sector':'chưa phân loại','rs_market':None,'rs_sector':None,'rs_percentile':None}
            m=members(universe,dates[-1]);m=m.loc[m.symbol.eq(s)]
            if len(m)==1:r['sector']=m.iloc[0].sector or 'chưa phân loại'
            if s in set(raw.symbol):r['price_basis']='RAW_VND_IMPORTED; score chưa điều chỉnh quyền'
            if len(dates)>=21 and r.get('return20') is not None:
                b=bench.loc[(bench.symbol=='VNINDEX')&(bench.known_at<=asof)].set_index('date')
                if dates[-1] in b.index and dates[-21] in b.index:r['rs_market']=(1+r['return20'])/(b.loc[dates[-1],'close']/b.loc[dates[-21],'close'])-1
            items.append(r)
    rank=pd.Series({r['symbol']:r['rs_market'] for r in items}).dropna().rank(pct=True)*100
    for r in items:
        r['rs_percentile']=rank.get(r['symbol'],None)
        peers=[x['return20'] for x in items if x.get('return20') is not None and x['sector']==r['sector'] and x['as_of']==r['as_of']]
        if r['sector']!='chưa phân loại' and len(peers)>=2 and r.get('return20') is not None:r['rs_sector']=(1+r['return20'])/(1+np.mean(peers))-1
    result=safe({'items':items,'count':len(items),'computed':computed,'seconds':time.perf_counter()-started,'cache':'disk/per-symbol','warning':'Điểm quy tắc không phải xác suất. RS ngành dùng trung bình các mã có dữ liệu, chưa phải chỉ số ngành PIT đầy đủ.'})
    if rev and rev==db_revision(path):_hot.update(key=key,value=result)
    return result

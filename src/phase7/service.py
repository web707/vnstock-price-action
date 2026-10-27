import time
import numpy as np
import pandas as pd
from src.phase7.data import snapshot,reference,benchmark,sector_at,ref_signature,safe,valid
from src.phase7.features import features,weekly,WEIGHTS
from src.data_quality import assess
from src.discovery import RevisionCache,db_revision
cache=RevisionCache(maxsize=32,ttl=120)

def detail(path,symbol):
    snap=snapshot(path);f=snap['frames'].get(symbol)
    if f is None or f.empty:raise ValueError('Không có dữ liệu cho mã '+symbol)
    if not valid(f):raise ValueError('OHLCV/ngày không hợp lệ; dừng phân tích')
    i=features(f);w=weekly(f);wi=features(w) if len(w)>=60 else None
    candles=f.tail(180).copy();candles['date']=candles.TRADE_DATE.dt.strftime('%Y-%m-%d')
    for col in ['ma20','ma50','support','resistance']:candles[col]=i.loc[candles.index,col]
    b=benchmark();rs=None
    if len(f)>20 and b is not None and f.TRADE_DATE.iloc[-1] in b.index and f.TRADE_DATE.iloc[-21] in b.index:rs=f.CLOSE_PRICE.iloc[-1]/f.CLOSE_PRICE.iloc[-21]-b.loc[f.TRADE_DATE.iloc[-1]]/b.loc[f.TRADE_DATE.iloc[-21]]
    return safe({'symbol':symbol,'as_of':str(f.TRADE_DATE.iloc[-1].date()),'daily':i.iloc[-1].to_dict(),'weekly':wi.iloc[-1].to_dict() if wi is not None else None,'weights':WEIGHTS.get(i.regime.iloc[-1]),'rs_vs_vnindex':rs,'quality':assess(f),'candles':candles[['date','OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE','VOLUME','ma20','ma50','support','resistance']].to_dict('records'),'warnings':['Điểm quy tắc không phải xác suất. Giá và cơ sở điều chỉnh chưa xác minh.','Swing chỉ công bố sau 3 nến phải. VCP/pullback/phân kỳ là heuristic.','Khung tuần loại tuần đang diễn ra; dữ liệu ngày hiện tại bị loại.']})

def dashboard(path):
    started=time.perf_counter();rev=db_revision(path);key=(rev,ref_signature(),str(pd.Timestamp.now(tz='Asia/Ho_Chi_Minh').date())) if rev else None
    old=cache.get(key)
    if old is not None:old['cache_hit']=True;old['request_seconds']=time.perf_counter()-started;return old
    snap=snapshot(path);frames=snap['frames'];asof=max(f.TRADE_DATE.max() for f in frames.values());refs=reference('sectors');b=benchmark();rows=[]
    for s,f in frames.items():
        q=assess(f)
        if len(f)<60 or q['status']=='INVALID':rows.append({'symbol':s,'status':q['status'] if q['status']=='INVALID' else 'INSUFFICIENT','score':None});continue
        i=features(f);v=i.iloc[-1];same=f.TRADE_DATE.iloc[-1]==asof
        row={'symbol':s,'as_of':str(f.TRADE_DATE.iloc[-1].date()),'same_session':bool(same),'status':q['status'],'score':v.adaptive_score,'regime':v.regime,'close':f.CLOSE_PRICE.iloc[-1],'return20':v.return20,'volume_ratio':v.volume_ratio,'above50':bool(f.CLOSE_PRICE.iloc[-1]>v.ma50) if pd.notna(v.ma50) else None,'above200':bool(f.CLOSE_PRICE.iloc[-1]>v.ma200) if pd.notna(v.ma200) else None,'sector':sector_at(refs,s,asof),'rs_benchmark':None,'rs_sector':None,'rs_percentile':None,'rs_sector_percentile':None}
        if b is not None and len(f)>20 and f.TRADE_DATE.iloc[-1] in b.index and f.TRADE_DATE.iloc[-21] in b.index:row['rs_benchmark']=v.return20-(b.loc[f.TRADE_DATE.iloc[-1]]/b.loc[f.TRADE_DATE.iloc[-21]]-1)
        rows.append(row)
    current=[r for r in rows if r.get('same_session')]
    def breadth(k):
        group=[r for r in current if r[k] is not None];return {'percent':100*sum(r[k] for r in group)/len(group) if group else None,'denominator':len(group)}
    def rank(group,key,target):
        for r,p in zip(group,pd.Series([r[key] for r in group],dtype=float).rank(pct=True)):r[target]=100*p
    rank([r for r in current if r['rs_benchmark'] is not None],'rs_benchmark','rs_percentile')
    sectors=[]
    for sector in sorted({r['sector'] for r in current if r['sector']}):
        group=[r for r in current if r['sector']==sector and pd.notna(r['return20'])]
        if len(group)<2:continue
        avg=np.mean([r['return20'] for r in group]);sectors.append({'sector':sector,'return20_equal_weight':avg,'members':len(group)})
        for r in group:r['rs_sector']=r['return20']-avg
        rank(group,'rs_sector','rs_sector_percentile')
    regime='UNAVAILABLE_NO_INDEX_OHLC';idx=reference('benchmark')
    if {'DATE','OPEN','HIGH','LOW','CLOSE','VOLUME'}.issubset(idx):
        idx=idx.rename(columns={'DATE':'TRADE_DATE','OPEN':'OPEN_PRICE','HIGH':'HIGH_PRICE','LOW':'LOW_PRICE','CLOSE':'CLOSE_PRICE'});idx.TRADE_DATE=pd.to_datetime(idx.TRADE_DATE);idx=idx.loc[idx.TRADE_DATE<=asof].sort_values('TRADE_DATE').reset_index(drop=True)
        if len(idx)>=100 and idx.TRADE_DATE.iloc[-1]==asof and valid(idx):
            regime=features(idx).regime.iloc[-1];b50=breadth('above50')['percent']
            if b50 is not None and ((regime=='UPTREND' and b50<50) or (regime=='DOWNTREND' and b50>50)):regime='MIXED_INDEX_BREADTH'
    rows=safe(rows);rows.sort(key=lambda r:(not r.get('same_session',False),-(r.get('score') or 0),r['symbol']))
    result=safe({'as_of':str(asof.date()),'scope':'Độ rộng của snapshot cùng phiên, không đại diện toàn thị trường; universe chưa point-in-time.','universe_count':len(snap['catalog']),'with_prices':len(frames),'missing_symbols':[s for s in snap['catalog'].SYMBOL if s not in frames],'breadth50':breadth('above50'),'breadth200':breadth('above200'),'market_regime':regime,'sectors':sorted(sectors,key=lambda s:-s['return20_equal_weight']),'items':rows,'cache_hit':False,'compute_seconds':time.perf_counter()-started})
    cache.put(key,result);return result

def health(path,symbol):
    snap=snapshot(path);f=snap['frames'].get(symbol)
    if f is None:raise ValueError('Không có mã')
    cal=reference('calendar');missing=None
    if 'DATE' in cal:
        days=pd.DatetimeIndex(pd.to_datetime(cal.DATE));missing=[str(d.date()) for d in days[(days>=f.TRADE_DATE.min())&(days<=f.TRADE_DATE.max())] if d not in set(f.TRADE_DATE)]
    jumps=f.loc[f.CLOSE_PRICE.pct_change(fill_method=None).abs()>.2,['TRADE_DATE','CLOSE_PRICE']].copy();jumps['TRADE_DATE']=jumps.TRADE_DATE.dt.strftime('%Y-%m-%d')
    events=snap['events'].loc[snap['events'].SYMBOL.eq(symbol)]
    return safe({'symbol':symbol,'quality':assess(f),'missing_sessions':missing,'missing_note':'Cần calendar.csv để xác định thiếu phiên; ngày thường không phải lịch sở giao dịch.','jumps':jumps.to_dict('records'),'events':events.to_dict('records'),'corporate_action_status':'UNVERIFIED','warning':'Không tự sửa giá theo sự kiện Yahoo; cần đối chiếu cơ sở RAW/adjusted.'})

def compare(path,symbols):
    snap=snapshot(path);series={}
    for s in dict.fromkeys(symbols):
        f=snap['frames'].get(s)
        if f is None or not valid(f):raise ValueError('Thiếu hoặc lỗi dữ liệu '+s)
        series[s]=pd.Series(f.CLOSE_PRICE.to_numpy(),index=f.TRADE_DATE)
    aligned=pd.DataFrame(series).dropna().tail(252)
    if len(aligned)<31:raise ValueError('Cần 31 ngày chung để tính tương quan')
    return safe({'symbols':list(series),'sessions':len(aligned),'correlation':aligned.pct_change(fill_method=None).dropna().corr().to_dict(),'normalized_100':(aligned/aligned.iloc[0]*100).rename_axis('date').reset_index().to_dict('records'),'warning':'Tương quan lịch sử không là tương quan tương lai; giá chưa xác minh.'})

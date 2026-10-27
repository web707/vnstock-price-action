import pandas as pd
import numpy as np
from src.phase8.data import connect,read,members,adjusted,update_plan,covered
from src.phase8.fast import scan
from src.phase7.data import safe

def health(path):
    with connect(path,True) as db:
        f=pd.read_sql_query('SELECT SYMBOL,TRADE_DATE,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,CLOSE_PRICE,VOLUME FROM STOCK_PRICES ORDER BY SYMBOL,TRADE_DATE',db)
        catalog=[r[0] for r in db.execute('SELECT SYMBOL FROM STOCK_SYMBOLS')]
        events=db.execute('SELECT COUNT(*) FROM STOCK_EVENTS').fetchone()[0]
    u=read(path,'universe');raw=read(path,'prices');cal=read(path,'calendar');actions=read(path,'actions');today=pd.Timestamp.now(tz='Asia/Ho_Chi_Minh').normalize().tz_localize(None);rows=[];unknown=[];adjustments=[]
    for s,g in f.groupby('SYMBOL',sort=False):
        d=pd.to_datetime(g.TRADE_DATE);jump=g.CLOSE_PRICE.pct_change(fill_method=None).abs().gt(.2);age=(today-d.max()).days
        uu=u.loc[u.symbol==s];known_days=set()
        for r in uu.itertuples():known_days.update(d[(d>=r.valid_from)&(d<=(r.valid_to or '2262-01-01'))&(d>=r.known_at)].dt.strftime('%Y-%m-%d'))
        if len(known_days)<len(d):unknown.append({'symbol':s,'start':str(d.min().date()),'end':str(d.max().date()),'rows_without_pit':len(d)-len(known_days),'impact':'Không lượng hóa được survivorship bias'})
        for year,part in g.groupby(d.dt.year):
            dd=pd.to_datetime(part.TRADE_DATE);expected=set(cal.loc[(cal.date>=str(dd.min().date()))&(cal.date<=str(dd.max().date())),'date']);missing=sorted(expected-set(dd.dt.strftime('%Y-%m-%d')))
            bad=(part[['OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE']]<=0).any(axis=1)|(part.HIGH_PRICE<part[['OPEN_PRICE','CLOSE_PRICE']].max(axis=1))|(part.LOW_PRICE>part[['OPEN_PRICE','CLOSE_PRICE']].min(axis=1))|~np.isfinite(part[['OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE','VOLUME']]).all(axis=1)
            rows.append({'symbol':s,'year':int(year),'rows':len(part),'first':str(dd.min().date()),'last':str(dd.max().date()),'age_days':int(age),'missing_sessions':len(missing) if expected else None,'missing_dates':missing,'zero_volume':int(part.VOLUME.eq(0).sum()),'invalid_prices':int(bad.sum()),'jumps_gt20pct':int(jump.loc[part.index].sum()),'raw_rows_imported':int(((raw.symbol==s)&raw.date.str.startswith(str(year))).sum()),'basis':'LEGACY_UNKNOWN','coverage_note':'Chỉ đo giữa phiên đầu/cuối đã quan sát; chưa bao gồm đầu/cuối năm thiếu niêm yết'})
    for s,g in raw.groupby('symbol'):
        _,applied=adjusted(g,actions.loc[actions.symbol==s],str(today.date()));adjustments.extend([{'symbol':s,**a} for a in applied])
    return safe({'as_of':str(today.date()),'items':rows,'priced_symbols':f.SYMBOL.nunique(),'catalog_symbols':len(catalog),'catalog_without_prices':sorted(set(catalog)-set(f.SYMBOL)),'universe_gaps':unknown,'survivorship_bias_resolved':False,'benchmark_rows':len(read(path,'benchmarks')),'calendar_rows':len(cal),'imported_actions':len(actions),'legacy_events_unverified':events,'adjustment_preview':adjustments,'warnings':['Chưa có dữ liệu không có nghĩa là không có vấn đề.','Nhảy giá chỉ là cờ cần kiểm tra, không tự suy ra chia tách/cổ tức.','Các bảng RAW nhập riêng; không sửa giá legacy, không tự áp dụng dữ liệu quyền legacy chưa xác minh.']})

def replay_data(path,symbols):
    from src.phase8.execution import compare
    from src.phase7.features import features
    raw=read(path,'prices');u=read(path,'universe');cal=read(path,'calendar');lim=read(path,'limits');act=read(path,'actions');cov=read(path,'coverage');missing=[]
    if cal.empty:missing.append('calendar')
    frames=[];orders=[]
    for s in symbols:
        f=raw.loc[raw.symbol==s].sort_values('date')
        if len(f)<210:missing.append(s+': ít hơn 210 phiên RAW_VND');continue
        if not covered(cov,'ACTIONS',s,f.date.min(),f.date.max()):missing.append(s+': thiếu coverage quyền')
        if len(lim.loc[lim.symbol==s])<len(f):missing.append(s+': thiếu trần/sàn từng ngày')
        if any(members(u,d).loc[lambda z:z.symbol==s].empty for d in f.date):missing.append(s+': thiếu PIT')
        if not set(f.date)<=set(cal.date):missing.append(s+': lịch phiên thiếu')
        if not missing:
            merged=f.merge(lim.loc[lim.symbol==s,['symbol','date','floor','ceiling']],on=['symbol','date'],how='left')
            ff=f.rename(columns={'date':'TRADE_DATE','open':'OPEN_PRICE','high':'HIGH_PRICE','low':'LOW_PRICE','close':'CLOSE_PRICE','volume':'VOLUME'});i=features(ff);above=ff.CLOSE_PRICE>i.ma50
            for j in range(200,len(f)-1):
                if above.iloc[j]!=above.iloc[j-1]:orders.append({'symbol':s,'signal_date':f.date.iloc[j],'date':f.date.iloc[j+1],'side':'BUY' if above.iloc[j] else 'SELL','qty':100})
            frames.append(merged)
    if missing:return {'status':'BLOCKED','missing':missing,'reason':'Không dùng giá legacy làm RAW hoặc giả lập dữ liệu tham chiếu còn thiếu.'}
    return {'status':'RESEARCH_ONLY','strategy':'MA50 cross, fixed 100 shares; exogenous orders',**compare(pd.concat(frames),orders,cal.date,u,act)}

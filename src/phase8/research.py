"""Pooled causal labels, date-based purged walk-forward and conservative inference."""
import os,json,hashlib,sqlite3
from pathlib import Path
import pandas as pd
import numpy as np
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss
from src.phase7.features import features,FEATURES
from src.phase7.data import safe
from src.phase8.data import read,connect,members,covered,adjusted

def split_dates(dates,horizon=10,train=1260,validation=252,test=252,mode='expanding',embargo=10):
    if mode not in ['expanding','rolling'] or min(horizon,train,validation,test)<1 or embargo<horizon:raise ValueError('Invalid split / embargo phải >= horizon')
    d=pd.DatetimeIndex(sorted(set(dates)))
    for start in range(train+validation+2*embargo,len(d)-horizon,test):
        va=start-validation-embargo;tr_end=va-embargo
        yield {'train':(d[max(0,tr_end-train)] if mode=='rolling' else d[0],d[tr_end]),'validation':(d[va],d[start-embargo]),'test':(d[start],d[min(start+test,len(d)-horizon)])}

def purged_ids(samples,bounds,next_start):
    a,b=bounds
    return samples.index[(samples.date>=a)&(samples.date<b)&(samples.end<next_start)].to_numpy()
def inference(values,configs=1,runs=1000,seed=7):
    a=np.asarray(values,float);a=a[np.isfinite(a)];n=len(a)
    if n<20:return {'dates':n,'mean_difference':float(a.mean()) if n else None,'ci95':None,'p_adjusted':None}
    rng=np.random.default_rng(seed);block=max(2,int(np.sqrt(n)));means=[];null=[]
    for _ in range(runs):
        starts=rng.integers(0,n,size=int(np.ceil(n/block)));ids=np.concatenate([(s+np.arange(block))%n for s in starts])[:n]
        means.append(a[ids].mean());null.append((a-a.mean())[ids].mean())
    p=(1+np.sum(np.abs(null)>=abs(a.mean())))/(runs+1)
    return {'dates':n,'mean_difference':float(a.mean()),'ci95':np.quantile(means,[.025,.975]).tolist(),'p_raw':p,'p_adjusted':min(1,p*configs*4),'block_dates':block,'runs':runs,'warning':'CI mô tả, chưa điều chỉnh multiple testing; p Bonferroni 4 phép so sánh × cấu hình.'}
def permutation(obs,configs=1,runs=1000,seed=7):
    groups=[g for _,g in obs.groupby('date') if 0<g.selected.sum()<len(g)]
    if not groups:return {'dates':0,'p_adjusted':None}
    rng=np.random.default_rng(seed);actual=np.mean([g.loc[g.selected,'net'].mean()-g.net.mean() for g in groups]);null=np.zeros(runs)
    for g in groups:
        a=g.net.to_numpy();k=int(g.selected.sum())
        null+=np.array([rng.choice(a,k,replace=False).mean()-a.mean() for _ in range(runs)])/len(groups)
    p=(1+np.sum(abs(null)>=abs(actual)))/(runs+1)
    return {'dates':len(groups),'excess':actual,'p_raw':p,'p_adjusted':min(1,p*configs*4),'runs':runs,'warning':'Hoán vị mã trong cùng ngày, giữ số tín hiệu; cần giả định exchangeability có điều kiện.'}
def evidence(comparisons,permutation_result,data_ok,n_dates):
    reasons=[]
    if not data_ok:reasons.append('Thiếu RAW/PIT/quyền/benchmark hoặc có volume khớp lệnh bằng 0')
    if n_dates<100:reasons.append('Dưới 100 cụm ngày OOS; số dòng nhiều mã không phải số mẫu độc lập')
    valid=all(x.get('dates',0)>=100 and x.get('p_adjusted') is not None for x in comparisons.values()) and permutation_result.get('dates',0)>=100
    if not valid:reasons.append('Benchmark/kiểm định chưa đủ cụm ngày')
    if reasons:return 'Chưa đủ bằng chứng',reasons
    index=comparisons['VNINDEX']
    if index['p_adjusted']<.05 and index['mean_difference']<0:return 'Bằng chứng ngược',['Kém VNINDEX có ý nghĩa sau điều chỉnh; vẫn phụ thuộc chất lượng dữ liệu']
    if all(v['mean_difference']>0 and v['p_adjusted']<.05 for v in comparisons.values()) and permutation_result['excess']>0 and permutation_result['p_adjusted']<.05:return 'Có bằng chứng',['Vượt các đối chứng trong nghiên cứu nhãn OOS; chưa chứng minh P&L thực thi']
    return 'Chưa đủ bằng chứng',['Chưa vượt tất cả đối chứng có ý nghĩa sau multiple testing']

def run(path,symbols=('HPG','FPT','VNM','VCB','SSI','MWG'),horizon=10,C=1.,threshold=.55,mode='expanding',embargo=10,registry=None):
    if horizon not in [5,10,20] or not .01<=C<=10 or not .5<=threshold<=.9 or not 1<=len(set(symbols))<=40:raise ValueError('Invalid research parameters')
    symbols=list(dict.fromkeys(symbols));embargo=max(embargo,horizon);today=pd.Timestamp.now(tz='Asia/Ho_Chi_Minh').strftime('%Y-%m-%d');raw=read(path,'prices');u=read(path,'universe');actions=read(path,'actions');bench=read(path,'benchmarks');cov=read(path,'coverage')
    frames={};all_dates=set();raw_symbols=set()
    for s in symbols:
        r=raw.loc[(raw.symbol==s)&(raw.date<today)&(raw.known_at<=raw.date)].sort_values('date')
        if not r.empty:
            raw_symbols.add(s);r,_=adjusted(r,actions.loc[actions.symbol==s],today,causal=True)
            f=r.rename(columns={'date':'TRADE_DATE','adj_open':'OPEN_PRICE','adj_high':'HIGH_PRICE','adj_low':'LOW_PRICE','adj_close':'CLOSE_PRICE','volume':'VOLUME'})[['TRADE_DATE','OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE','VOLUME']].copy();f['QUALITY_STATUS']='VALID'
        else:
            with connect(path,True) as db:f=pd.read_sql_query('SELECT * FROM STOCK_PRICES WHERE SYMBOL=? AND TRADE_DATE<? ORDER BY TRADE_DATE',db,params=[s,today])
        if f.empty:continue
        f.TRADE_DATE=pd.to_datetime(f.TRADE_DATE);frames[s]=f.reset_index(drop=True);all_dates.update(f.TRADE_DATE)
    dates=pd.DatetimeIndex(sorted(all_dates))
    if len(dates)<1800:return {'status':'INSUFFICIENT_DATA','evidence':'Chưa đủ bằng chứng','oos_samples':0,'prediction':None,'reason':'Cần lịch sử train/validation/test dài hơn','folds':[]}
    grid=set(dates[200::horizon]);samples=[];last_features={};buyhold={}
    b=bench.loc[(bench.symbol=='VNINDEX')&(bench.known_at<=today)].set_index('date').close
    for s,f in frames.items():
        i=features(f);last_features[s]=(f,i);net=f.CLOSE_PRICE.shift(-horizon)*.999*.9975/(f.OPEN_PRICE.shift(-1)*1.001*1.0015)-1
        clean=f.get('QUALITY_STATUS',pd.Series('UNKNOWN',index=f.index)).eq('VALID').rolling(20).sum().eq(20)&f.VOLUME.gt(0).rolling(20).sum().eq(20)&i.ma200.notna()
        buyhold[s]=float(f.CLOSE_PRICE.iloc[-1]/f.CLOSE_PRICE.iloc[0]-1)
        for j in range(200,len(f)-horizon):
            d=f.TRADE_DATE.iloc[j]
            if d not in grid or not clean.iloc[j] or not np.isfinite(net.iloc[j]):continue
            membership=members(u,d);m=membership.loc[membership.symbol==s];known_symbol=s in set(u.symbol)
            if known_symbol and m.empty:continue
            a=str(f.TRADE_DATE.iloc[j+1].date());e=str(f.TRADE_DATE.iloc[j+horizon].date())
            samples.append({'symbol':s,'date':d,'end':f.TRADE_DATE.iloc[j+horizon],'net':net.iloc[j],'actual':int(net.iloc[j]>0),'ma_selected':bool(f.CLOSE_PRICE.iloc[j]>i.ma50.iloc[j]),'market':float(b[e]/b[a]-1) if a in b.index and e in b.index else np.nan,'pit':len(m)==1,'sector':m.iloc[0].sector or 'chưa phân loại' if len(m)==1 else 'chưa phân loại','regime':i.regime.iloc[j],'liquidity':float(i.turnover20.iloc[j]) if s in raw_symbols else np.nan,'zero_execution_volume':bool(f.VOLUME.iloc[j+1]<=0 or f.VOLUME.iloc[j+horizon]<=0),**i[FEATURES].iloc[j].to_dict()})
    x=pd.DataFrame(samples)
    if x.empty:return {'status':'INSUFFICIENT_DATA','evidence':'Chưa đủ bằng chứng','oos_samples':0,'folds':[]}
    x=x.sort_values(['date','symbol']).reset_index(drop=True);config={'symbols':sorted(symbols),'horizon':horizon,'C':C,'threshold':threshold,'mode':mode,'embargo':embargo};registry=registry or os.getenv('QTA8_RESEARCH_DB',str(Path(path).parent/'qta8_research.db'));Path(registry).parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(registry) as db:
        db.execute('CREATE TABLE IF NOT EXISTS configurations(key TEXT PRIMARY KEY,config TEXT,created TEXT)');key=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest();db.execute('INSERT OR IGNORE INTO configurations VALUES(?,?,?)',(key,json.dumps(config),today));configs=db.execute('SELECT COUNT(*) FROM configurations').fetchone()[0]
    dataset_digest=hashlib.sha256(x.to_csv(index=False).encode()).hexdigest()
    with sqlite3.connect(registry) as db:
        db.execute('CREATE TABLE IF NOT EXISTS experiments(config_key TEXT,dataset_digest TEXT,PRIMARY KEY(config_key,dataset_digest))');db.execute('INSERT OR IGNORE INTO experiments VALUES(?,?)',(key,dataset_digest));trials=db.execute('SELECT COUNT(*) FROM experiments').fetchone()[0]
    configs=max(configs,trials)
    folds=[];observations=[];last=None
    for num,part in enumerate(split_dates(dates,horizon=horizon,mode=mode,embargo=embargo),1):
        tr=purged_ids(x,part['train'],part['validation'][0]);va=purged_ids(x,part['validation'],part['test'][0]);te=purged_ids(x,part['test'],pd.Timestamp.max)
        row={'fold':num,'bounds':{k:[str(a.date()),str(b.date())] for k,(a,b) in part.items()},'samples':dict(zip(['train','validation','test'],map(len,[tr,va,te]))),'test_dates':int(x.loc[te,'date'].nunique())}
        if min(len(tr),len(va),len(te))<20 or len(tr)<200 or x.loc[tr,'actual'].nunique()<2 or x.loc[va,'actual'].nunique()<2:folds.append({**row,'status':'INSUFFICIENT'});continue
        model=make_pipeline(SimpleImputer(strategy='median',keep_empty_features=True),StandardScaler(),LogisticRegression(C=C,max_iter=600,random_state=7));weights=1/x.loc[tr].groupby('date').date.transform('count').to_numpy();weights*=len(tr)/weights.sum();model.fit(x.loc[tr,FEATURES],x.loc[tr,'actual'],logisticregression__sample_weight=weights)
        cal=LogisticRegression(C=1,max_iter=500,random_state=7);vweights=1/x.loc[va].groupby('date').date.transform('count').to_numpy();vweights*=len(va)/vweights.sum();cal.fit(model.decision_function(x.loc[va,FEATURES]).reshape(-1,1),x.loc[va,'actual'],sample_weight=vweights)
        probability=cal.predict_proba(model.decision_function(x.loc[te,FEATURES]).reshape(-1,1))[:,1];o=x.loc[te].copy();o['probability']=probability;o['selected']=probability>=threshold;o['fold']=num;observations.append(o);folds.append({**row,'status':'OOS','brier':brier_score_loss(o.actual,probability),'warning':'Dưới 100 cụm ngày' if row['test_dates']<100 else None});last=(model,cal,x.loc[va,'end'].max())
    if not observations:return {'status':'INSUFFICIENT_DATA','evidence':'Chưa đủ bằng chứng','oos_samples':0,'folds':folds}
    o=pd.concat(observations,ignore_index=True);chosen=o.loc[o.selected];daily=chosen.groupby('date').net.mean();base=o.groupby('date').net.mean();ma=o.loc[o.ma_selected].groupby('date').net.mean();market=chosen.groupby('date').market.mean()
    comparisons={'VNINDEX':inference(daily-market,configs),'eligible_buy_hold':inference(daily-base,configs),'MA50':inference(daily-ma,configs)};perm=permutation(o,configs);ndates=o.date.nunique();bins=[]
    for k in range(5):
        g=o.loc[(o.probability*5).astype(int).clip(upper=4)==k];v=g.groupby('date').actual.mean();q=inference(v,1)
        bins.append({'range':[k/5,(k+1)/5],'rows':len(g),'dates':len(v),'frequency':v.mean() if len(v) else None,'ci95':q['ci95']})
    reasons=[];start=str(o.date.min().date());end=str(o.end.max().date())
    if not set(frames)<=raw_symbols:reasons.append('Giá legacy chưa xác nhận RAW/đơn vị/quyền')
    if not o.pit.all() or not covered(cov,'UNIVERSE','ALL',start,end):reasons.append('Universe lịch sử chưa đầy đủ; survivorship bias chưa lượng hóa')
    if o.market.isna().any():reasons.append('Thiếu VNINDEX ở các ngày nhãn')
    if o.zero_execution_volume.any():reasons.append('Có nhãn không thể giả định khớp lệnh do volume = 0')
    if any(not covered(cov,'ACTIONS',s,start,end) for s in frames):reasons.append('Thiếu chứng nhận độ phủ dữ liệu quyền')
    if (actions.kind=='RIGHTS').any():reasons.append('Quyền mua chưa được đưa vào lợi suất nhãn theo dòng tiền thực tế')
    verdict,why=evidence(comparisons,perm,not reasons,ndates);model,cal,frozen=last;age=int((dates>frozen).sum());predictions={}
    for s,(f,i) in last_features.items():
        reason='; '.join(reasons) if reasons else ('Model quá cũ: '+str(age)+' phiên từ validation; cần huấn luyện lại' if age>252 else ('Dưới 100 cụm ngày OOS' if ndates<100 else None))
        p=float(cal.predict_proba(model.decision_function(i[FEATURES].tail(1)).reshape(-1,1))[0,1]);bucket=bins[min(int(p*5),4)]
        if bucket['dates']<30:reason=(reason+'; ' if reason else '')+'Bin calibration dưới 30 cụm ngày'
        if age>252 and (reason is None or 'Model quá cũ' not in reason):reason=(reason+'; ' if reason else '')+f'Model quá cũ: {age} phiên; cần huấn luyện lại'
        if not np.isfinite(i[FEATURES].iloc[-1]).all() or not f.VOLUME.tail(20).gt(0).all() or not f.QUALITY_STATUS.tail(20).eq('VALID').all():reason=(reason+'; ' if reason else '')+'Thiếu chỉ báo mới'
        contrib=model[:-1].transform(i[FEATURES].tail(1))[0]*model[-1].coef_[0]*cal.coef_[0,0]
        predictions[s]={'probability':None if reason else p,'abstention_reason':reason,'contributions_log_odds':dict(zip(FEATURES,contrib)),'intercept_log_odds':model[-1].intercept_[0]*cal.coef_[0,0]+cal.intercept_[0],'historical_bin':bucket}
    oos_buyhold={}
    for s,f in frames.items():
        g=o.loc[o.symbol==s]
        if g.empty:continue
        first=f.loc[f.TRADE_DATE>g.date.min()].iloc[0];lastrow=f.loc[f.TRADE_DATE<=g.end.max()].iloc[-1]
        oos_buyhold[s]={'start':str(first.TRADE_DATE.date()),'end':str(lastrow.TRADE_DATE.date()),'return':float(lastrow.CLOSE_PRICE/first.OPEN_PRICE-1),'basis':'open-to-close, no execution costs'}
    bm_start=str(o.date.min().date());bm_end=str(o.end.max().date());index_hold={'start':bm_start,'end':bm_end,'return':float(b[bm_end]/b[bm_start]-1) if bm_start in b.index and bm_end in b.index else None,'basis':'close-to-close, descriptive different entry convention'}
    strata={}
    o['liquidity_group']=np.select([o.liquidity<1e9,o.liquidity<1e10,o.liquidity>=1e10],['<1 tỷ','1–10 tỷ','>=10 tỷ'],default='chưa rõ đơn vị')
    for col in ['regime','sector','liquidity_group']:
        strata[col]=[{'group':str(k),'rows':len(g),'dates':g.date.nunique(),'selected':int(g.selected.sum()),'mean_selected':g.loc[g.selected,'net'].mean()} for k,g in o.groupby(col)]
    return safe({'status':'RESEARCH_ONLY','evidence':verdict,'reasons':why+reasons,'oos_samples':len(o),'oos_date_clusters':ndates,'selected':len(chosen),'folds':folds,'brier':brier_score_loss(o.actual,o.probability),'comparisons':comparisons,'permutation':perm,'calibration':bins,'strata':strata,'predictions':predictions,'model_frozen_at':str(frozen.date()),'model_age_sessions':age,'configurations_or_dataset_trials':configs,'dataset_digest':dataset_digest,'zero_execution_volume_rows':int(o.zero_execution_volume.sum()),'full_history_buy_hold_same_stock':buyhold,'oos_period_buy_hold_same_stock':oos_buyhold,'oos_period_buy_hold_VNINDEX':index_hold,'observations':o.drop(columns=FEATURES).assign(date=lambda z:z.date.dt.strftime('%Y-%m-%d'),end=lambda z:z.end.dt.strftime('%Y-%m-%d')).to_dict('records'),'limitations':['Nhãn open kế tiếp → close H phiên với giả định phí, không phải P&L engine thực thi.','Dòng nhiều mã cùng ngày tương quan; date clusters vẫn có phụ thuộc thời gian.','eligible_buy_hold = đối chứng mua tất cả mã đủ điều kiện cùng cửa sổ; full_history_buy_hold khác kỳ không dùng kiểm định.','MA50 chỉ so sánh những ngày cả hai có vị thế, không là equity curve liên tục.','Registry chỉ biết cấu hình tại máy này, không biết thử nghiệm ngoài hệ thống.','Cần nested validation khi chọn tham số; không tự chọn biến thể tốt nhất.']})

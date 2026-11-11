"""Reproducible descriptive comparison; no profitability/meaningfulness claim."""
import sys,json,logging
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from swing_detector import detect_result,SwingDetectorConfig,clean_data,compute_wilder_atr
from swing_detector.detector import left_qualified,pivot_qualified
from swing_detector_old import detect_swings as old_detect,SwingDetectorConfig as OldConfig
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/layer1'
AS_OF='2026-10-28 15:00:00+07:00'  # compare complete sessions; exclude current partial session
logging.basicConfig(level=logging.ERROR)

def old_frame(df,k,p):
    ss=old_detect(df,OldConfig(swing_left=p,swing_right=p,reversal_mult=k))
    rows=[]
    for s in ss:
        rows.append(dict(swing_id=s.swing_id,type=s.swing_type,price=s.extreme_price,
            extreme_time=df.Datetime.iloc[s.index],confirm_time=df.available_time.iloc[s.confirmed_at_index],
            atr_at_candidate=s.atr_at_extreme,threshold_T=s.threshold,confirm_delay_bars=s.lag_bars,
            index=s.index,confirm_index=s.confirmed_at_index))
    return pd.DataFrame(rows)

def enrich(s,df):
    s=s.copy()
    s['leg_ATR']=np.nan;s['spacing']=s['index'].diff()
    atr=compute_wilder_atr(df)
    if len(s)>1:
        prev=s['index'].to_numpy()[:-1].astype(int);den=atr[prev]
        s.loc[s.index[1:],'leg_ATR']=np.divide(np.abs(np.diff(s.price)),den,out=np.full(len(den),np.nan),where=den>0)
    s['day']=pd.to_datetime(s.confirm_time).dt.date.astype(str)
    return s

def metrics(s,days):
    median=lambda col: s[col].dropna().median() if s[col].notna().any() else np.nan
    return dict(count=len(s),swings_per_session=len(s)/days if days else None,
        median_leg_ATR=median('leg_ATR'),median_delay_bars=median('confirm_delay_bars'),
        median_spacing_bars=median('spacing'),noise_legs_lt1ATR=int((s.leg_ATR<1).sum()),
        eligible_noise_legs=int(s.leg_ATR.notna().sum()))

def regime(df):
    a=compute_wilder_atr(df);relative=pd.Series(a)/df.Close
    rank=relative.rolling(100,min_periods=40).rank(pct=True)
    move=(df.Close-df.Close.shift(20))/pd.Series(a).replace(0,np.nan)
    r=pd.Series('SIDEWAYS',index=df.index)
    r[move>=3]='UP';r[move<=-3]='DOWN';r[rank>=.9]='HIGH_VOL';r[move.isna()]='UNCLASSIFIED'
    return r

def chart(symbol,df,old,new,center,suffix):
    lo=max(0,center-22);hi=min(len(df),center+24)
    fig,(ax,av)=plt.subplots(2,1,figsize=(14,8),sharex=True,gridspec_kw={'height_ratios':[4,1]})
    for j in range(lo,hi):
        row=df.iloc[j];color='#168169' if row.Close>=row.Open else '#d24f58'
        ax.vlines(j,row.Low,row.High,color=color,lw=1)
        ax.add_patch(Rectangle((j-.3,min(row.Open,row.Close)),.6,max(abs(row.Close-row.Open),.5),facecolor=color,edgecolor=color))
        av.bar(j,row.Volume,color=color,width=.7)
    for s,name,color,marker in [(old,'Old','#8b45b3','^'),(new,'New','#f49313','o')]:
        cut=s[(s['index']>=lo)&(s['index']<hi)]
        ax.scatter(cut['index'],cut.price,s=100,marker=marker,facecolors='none',edgecolors=color,lw=1.8,label=name)
        for row in cut.itertuples():
            if row.confirm_index<hi:
                ax.plot([row.index,row.confirm_index],[row.price,row.price],':',color=color,alpha=.6)
                ax.scatter(row.confirm_index,row.price,marker='x',color=color)
    ticks=np.arange(lo,hi,max(1,(hi-lo)//7));av.set_xticks(ticks)
    av.set_xticklabels([df.Datetime.iloc[t].strftime('%d/%m %H:%M') for t in ticks],rotation=25,ha='right')
    ax.set_title(f'{symbol} | old / new Layer 1 | {suffix} | x = confirmation bar')
    ax.set_ylabel('Provider price (VND)');av.set_ylabel('Volume');ax.legend();ax.grid(alpha=.15)
    fig.tight_layout();name=f'{symbol}_{suffix}.png';fig.savefig(OUT/name,dpi=130);plt.close(fig);return name

def diff_records(symbol,df,old,new,result):
    records=[];ok={(s.type,int(s.index)):s for s in old.itertuples()};nk={(s.type,int(s.index)):s for s in new.itertuples()}
    for key in sorted(set(ok)|set(nk),key=lambda x:x[1]):
        a,b=ok.get(key),nk.get(key)
        if a and b and a.confirm_index==b.confirm_index:continue
        kind,i=key;row=a if a else b;v=df.High.to_numpy() if kind=='HIGH' else df.Low.to_numpy()
        reasons=[];trace=[]
        if a and not b:
            if i<13:reasons.append('ATR chưa đủ 14 TR tại cực trị')
            if i<3:reasons.append('Chưa đủ 3 nến trái')
            elif not left_qualified(v,i,3,kind):
                reasons.append('Không đạt pivot trái / first-tie: left='+str(v[i-3:i].tolist())+'; price='+str(v[i]))
            if i+3>=len(df):reasons.append('Chưa đủ 3 nến phải cuối dữ liệu')
            elif (v[i]<max(v[i+1:i+4]) if kind=='HIGH' else v[i]>min(v[i+1:i+4])):
                reasons.append('Không đạt pivot phải; right='+str(v[i+1:i+4].tolist()))
            trace=[e for e in result.events if i<=e['bar']<=a.confirm_index+4 and (e.get('type')==kind or e['reason']=='ambiguous_defer')]
            if any(e['reason']=='ambiguous_defer' and e['bar']==a.confirm_index for e in trace):reasons.append('Nến xác nhận cũ bị quy tắc ambiguous_defer chặn')
        elif b and not a:
            previous=old[old.confirm_index<=i]
            state=('LOW' if previous.iloc[-1].type=='HIGH' else 'HIGH') if len(previous) else 'INIT'
            reasons.append(f'Tại cực trị mới, trạng thái cũ tìm {state}; khác chuỗi ứng viên/luân phiên')
            trace=[e for e in result.events if e.get('extreme_index')==i]
        else:
            reasons.append(f'Cùng cực trị, xác nhận cũ bar {a.confirm_index}, mới bar {b.confirm_index}')
            trace=[e for e in result.events if min(a.confirm_index,b.confirm_index)<=e['bar']<=max(a.confirm_index,b.confirm_index)]
        if a and not b:
            states=[e for e in result.events if e['reason']=='state' and e['bar'] in (i,a.confirm_index)]
            trace+=states
            for st in states:
                candidate=st['candidates'].get(kind)
                if st['state'] not in ('INIT',kind):
                    reasons.append(f"bar {st['bar']}: máy mới tìm {st['state']}, không nhận {kind}")
                elif candidate is not None and candidate['index']!=i:
                    reasons.append(f"bar {st['bar']}: ứng viên mới là bar {candidate['index']}, giá {candidate['price']}, T={candidate['threshold_T']:.4f}; reversal={candidate['reversal']:.4f}")
                elif candidate is not None and candidate['reversal']<candidate['threshold_T']:
                    reasons.append(f"bar {st['bar']}: đảo chiều {candidate['reversal']:.4f} < T={candidate['threshold_T']:.4f}")
        if not reasons:reasons=['Xem trace trạng thái; chưa phân lập nguyên nhân bằng ablation']
        records.append(dict(symbol=symbol,status='old_only' if not b else ('new_only' if not a else 'confirmation_changed'),
            type=kind,index=i,extreme_time=str(row.extreme_time),price=row.price,
            old_confirm=str(a.confirm_time) if a else None,new_confirm=str(b.confirm_time) if b else None,
            reasons=' | '.join(dict.fromkeys(reasons)),new_trace=json.dumps(trace,ensure_ascii=False)))
    return records

def main():
    summaries=[];regimes=[];daily=[];diffs=[];plots=[];pools={};pooldays={};health={}
    paths=[('HPG_SNAPSHOT',ROOT/'data/hpg_15m_sample.csv')]+[(s,OUT/'fetched'/f'{s}.csv') for s in ['HPG','FPT','VNM','VCB','SSI']]
    for symbol,path in paths:
        if not path.exists():continue
        raw=pd.read_csv(path);df,diag=clean_data(raw,as_of=AS_OF);health[symbol]=diag
        rr=regime(df);df.assign(regime=rr).to_csv(OUT/f'{symbol}_clean.csv',index=False)
        days=sorted(df.Datetime.dt.date.astype(str).unique());base=None
        for p in [3,5]:
            for k in [1.5,2.,2.5]:
                cfg=SwingDetectorConfig(ticker=symbol,pivot_left=p,pivot_right=p,reversal_atr_mult=k)
                result=detect_result(df,cfg)
                new=result.swings.rename(columns={'swing_type':'type','extreme_price':'price','confirmed_at':'confirm_time','atr_at_extreme':'atr_at_candidate'}).copy();new['index']=[i for i,t in result.indices];new['confirm_index']=[t for i,t in result.indices]
                new=enrich(new,df);old=enrich(old_frame(df,k,p),df)
                for version,s in [('old',old),('new',new)]:
                    s['regime']=rr.iloc[s.confirm_index.to_numpy(dtype=int)].to_numpy()
                    summaries.append(dict(symbol=symbol,version=version,k=k,pivot=p,**metrics(s,len(days))))
                    s.to_csv(OUT/f'{symbol}_{version}_k{k}_p{p}.csv',index=False)
                    counts=s.groupby('day').size()
                    for day in days:daily.append(dict(symbol=symbol,version=version,k=k,pivot=p,day=day,count=int(counts.get(day,0))))
                    for group in ['UP','DOWN','SIDEWAYS','HIGH_VOL','UNCLASSIFIED']:
                        sub=s[s.regime==group];exposure=df.loc[rr==group,'Datetime'].dt.date.nunique()
                        regimes.append(dict(symbol=symbol,version=version,k=k,pivot=p,regime=group,exposure_sessions=exposure,**metrics(sub,exposure)))
                if symbol!='HPG_SNAPSHOT':
                    pools.setdefault((k,p),[]).append(new);pooldays[(k,p)]=pooldays.get((k,p),0)+len(days)
                if k==2 and p==3:
                    base=(old,new,result);diffs.extend(diff_records(symbol,df,old,new,result))
                    (OUT/f'{symbol}_events.json').write_text(json.dumps(result.events,ensure_ascii=False,indent=2),encoding='utf-8')
        old,new,result=base
        own=[d for d in diffs if d['symbol']==symbol];center=own[len(own)//2]['index'] if own else len(df)//2
        plots.append(chart(symbol,df,old,new,center,'difference'))
        if symbol=='HPG':
            noise=new[new.leg_ATR<1]
            if len(noise):plots.append(chart(symbol,df,old,new,int(noise.iloc[0]['index']),'leg_lt1ATR'))
            for group in ['UP','DOWN','SIDEWAYS','HIGH_VOL']:
                idx=rr[rr==group].index
                if len(idx):plots.append(chart(symbol,df,old,new,int(idx[len(idx)//2]),group))
        print(symbol,len(df),len(old),len(new),flush=True)
    pd.DataFrame(summaries).to_csv(OUT/'comparison_summary.csv',index=False)
    pd.DataFrame(regimes).to_csv(OUT/'comparison_regimes.csv',index=False)
    pd.DataFrame(daily).to_csv(OUT/'swings_per_session.csv',index=False)
    pd.DataFrame(diffs).to_csv(OUT/'differences.csv',index=False)
    pooled=[dict(k=k,pivot=p,**metrics(pd.concat(items,ignore_index=True),pooldays[(k,p)])) for (k,p),items in pools.items()]
    pd.DataFrame(pooled).to_csv(OUT/'sensitivity_pooled.csv',index=False)
    (OUT/'health.json').write_text(json.dumps(health,ensure_ascii=False,indent=2),encoding='utf-8')
    html='<meta charset="utf-8"><title>Layer 1 comparison</title><style>body{font:15px sans-serif;margin:30px}table{border-collapse:collapse}td,th{padding:6px;border:1px solid #ddd}img{max-width:100%}</style><h1>Layer 1 — so sánh mô tả, không phải bằng chứng lợi nhuận</h1>'
    html+='<p>Đọc LAYER1_REPORT.md để biết giới hạn, định nghĩa chỉ tiêu và quy ước thời gian.</p>'
    html+=pd.DataFrame(summaries).to_html(index=False)+pd.DataFrame(diffs).drop(columns=['new_trace'],errors='ignore').to_html(index=False)
    html+=''.join(f'<h2>{p}</h2><img src="{p}">' for p in plots)
    (OUT/'comparison.html').write_text(html,encoding='utf-8')
if __name__=='__main__':main()

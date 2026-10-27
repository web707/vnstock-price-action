"""Purged walk-forward regularized logistic regression, validation-only calibration."""
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss,roc_auc_score,log_loss
from src.phase7.features import features,FEATURES

def partitions(n,horizon=10,train=800,validation=250,test=250):
    for t in range(200+train+validation+2*horizon,n-horizon,test):
        yield {'train':(200,t-validation-2*horizon),'validation':(t-validation-horizon,t-horizon),'test':(t,min(t+test,n-horizon))}

def wilson(wins,n):
    if not n:return None
    p=wins/n;z=1.96;den=1+z*z/n;mid=(p+z*z/(2*n))/den;half=z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [mid-half,mid+half]

def bootstrap(returns,seed=7,runs=300):
    a=np.asarray(returns,dtype=float);a=a[np.isfinite(a)]
    if len(a)<20:return {'status':'INSUFFICIENT_SAMPLES','samples':len(a)}
    rng=np.random.default_rng(seed);block=max(2,int(np.sqrt(len(a))));terminal=[];dd=[]
    for _ in range(runs):
        starts=rng.integers(0,len(a)-block+1,int(np.ceil(len(a)/block)));sample=np.concatenate([a[s:s+block] for s in starts])[:len(a)]
        curve=np.r_[1,np.cumprod(1+sample)];terminal.append(curve[-1]-1);dd.append((curve/np.maximum.accumulate(curve)-1).min())
    return {'status':'DESCRIPTIVE_BOOTSTRAP','samples':len(a),'runs':runs,'seed':seed,'block':block,'terminal_return_p05_p50_p95':np.quantile(terminal,[.05,.5,.95]).tolist(),'drawdown_p05_p50_p95':np.quantile(dd,[.05,.5,.95]).tolist(),'warning':'Resampling lợi suất đã quan sát, không phải kiểm định chiến lược thắng do may rủi; không tính thay đổi universe/khớp lệnh.'}

def walk_forward(f,benchmark=None,horizon=10,C=1.,threshold=.55):
    if horizon not in (5,10,20) or not .01<=C<=10 or not .5<=threshold<=.9:raise ValueError('Thông số mô hình không hợp lệ')
    f=f.sort_values('TRADE_DATE').reset_index(drop=True);i=features(f);x=i[FEATURES];dates=pd.to_datetime(f.TRADE_DATE)
    net=f.CLOSE_PRICE.shift(-horizon)*(.999)*(.9975)/(f.OPEN_PRICE.shift(-1)*1.001*1.0015)-1
    y=net.gt(0).astype(int)
    # Eligibility uses only information available at signal close.
    clean=f.get('QUALITY_STATUS',pd.Series('UNKNOWN',index=f.index)).eq('VALID').rolling(20).sum().eq(20)&f.VOLUME.gt(0).rolling(20).sum().eq(20)&i.ma200.notna()
    grid=np.arange(200,len(f)-horizon,horizon);folds=[];observations=[];last=None
    for number,part in enumerate(partitions(len(f),horizon),1):
        ids={k:np.array([j for j in grid if a<=j<b and clean.iloc[j] and np.isfinite(net.iloc[j])],dtype=int) for k,(a,b) in part.items()}
        tr,va,te=(ids[k] for k in ('train','validation','test'))
        row={'fold':number,'boundaries':{k:[str(dates.iloc[a].date()),str(dates.iloc[b-1].date())] for k,(a,b) in part.items()},'samples':{k:len(v) for k,v in ids.items()}}
        if len(tr)<60 or len(va)<20 or len(te)<5 or y.iloc[tr].nunique()<2 or y.iloc[va].nunique()<2:folds.append({**row,'status':'INSUFFICIENT_OR_ONE_CLASS'});continue
        pipe=make_pipeline(SimpleImputer(strategy='median'),StandardScaler(),LogisticRegression(C=C,max_iter=500,random_state=7));pipe.fit(x.iloc[tr],y.iloc[tr])
        calibrator=LogisticRegression(C=1.,max_iter=500,random_state=7).fit(pipe.decision_function(x.iloc[va]).reshape(-1,1),y.iloc[va])
        prob=calibrator.predict_proba(pipe.decision_function(x.iloc[te]).reshape(-1,1))[:,1];raw=pipe.predict_proba(x.iloc[te])[:,1]
        for j,p in zip(te,prob):
            br=None
            if benchmark is not None and dates.iloc[j+1] in benchmark.index and dates.iloc[j+horizon] in benchmark.index:br=float(benchmark.loc[dates.iloc[j+horizon]]/benchmark.loc[dates.iloc[j+1]]-1)
            observations.append({'signal_date':str(dates.iloc[j].date()),'probability':float(p),'actual':int(y.iloc[j]),'net_return':float(net.iloc[j]),'benchmark_return':br,'selected':bool(p>=threshold),'fold':number,'execution_volume_zero':bool(f.VOLUME.iloc[j+1]<=0 or f.VOLUME.iloc[j+horizon]<=0)})
        folds.append({**row,'status':'OOS','brier':brier_score_loss(y.iloc[te],prob),'raw_brier':brier_score_loss(y.iloc[te],raw),'prior_brier':brier_score_loss(y.iloc[te],np.full(len(te),y.iloc[tr].mean())),'auc':roc_auc_score(y.iloc[te],prob) if y.iloc[te].nunique()==2 else None})
        last=(pipe,calibrator,part['validation'][1]-1)
    if not observations:return {'status':'INSUFFICIENT_DATA','folds':folds,'prediction':None,'oos_samples':0}
    bins=[]
    for k in range(5):
        rows=[r for r in observations if min(int(r['probability']*5),4)==k];n=len(rows);wins=sum(r['actual'] for r in rows)
        bins.append({'lower':k/5,'upper':(k+1)/5,'count':n,'predicted_mean':np.mean([r['probability'] for r in rows]) if n else None,'observed_frequency':wins/n if n else None,'wilson95':wilson(wins,n)})
    pipe,calibrator,frozen=last;prediction=None
    if clean.iloc[-1] and len(f)-1-frozen<=252:
        z=pipe[:-1].transform(x.iloc[[-1]])[0];cc=calibrator.coef_[0,0];contrib=z*pipe[-1].coef_[0]*cc;intercept=pipe[-1].intercept_[0]*cc+calibrator.intercept_[0]
        p=float(calibrator.predict_proba(pipe.decision_function(x.iloc[[-1]]).reshape(-1,1))[0,1]);bucket=bins[min(int(p*5),4)]
        prediction={'probability':p,'reliability':'LOW' if bucket['count']<30 or len(observations)<60 else 'RESEARCH_ONLY','historical_bin':bucket,'contributions_log_odds':dict(zip(FEATURES,contrib.tolist())),'intercept_log_odds':float(intercept)}
    selected=[r for r in observations if r['selected']];matched=[r for r in selected if r['benchmark_return'] is not None];prob=[r['probability'] for r in observations];actual=[r['actual'] for r in observations]
    return {'status':'CHUA_CO_BANG_CHUNG_HIEU_QUA','folds':folds,'oos_samples':len(observations),'oos_brier':brier_score_loss(actual,prob),'oos_log_loss':log_loss(actual,prob,labels=[0,1]),'calibration_bins':bins,'observations':observations,'prediction':prediction,'model_frozen_at':str(dates.iloc[frozen].date()),'abstention_reason':None if prediction else 'Model quá cũ (>252 phiên từ validation) hoặc dữ liệu mới không đạt nhãn/volume; không xuất xác suất hiện tại.',
        'selected_count':len(selected),'mean_selected_net_return':np.mean([r['net_return'] for r in selected]) if selected else None,'benchmark_matched':len(matched),'excess_mean':np.mean([r['net_return']-r['benchmark_return'] for r in matched]) if matched else None,'monte_carlo':bootstrap([r['net_return'] for r in selected]),
        'limitations':['Mô hình dự báo nhãn lợi suất dương open kế tiếp đến close H phiên, không là xác suất thắng VN-Index.',
        'Phí mỗi chiều 0,15%, thuế bán 0,1%, trượt giá mỗi chiều 0,1% là giả định. Đây là nghiên cứu nhãn; không áp dụng engine khớp lệnh danh mục.',
        'Eligibility chỉ dùng dữ liệu tại tín hiệu; giữ cả mẫu có volume thực hiện bằng 0 và gắn cờ, nên lợi suất nhãn không là lợi suất giao dịch được.',
        'Chưa loại trừ survivorship bias, giá điều chỉnh sai và thiếu phiên. Benchmark close-to-close không khớp hoàn toàn giá vào open.',
        'Wilson là khoảng tần suất trong bin OOS, không phải khoảng dự báo cá nhân. Đóng góp log-odds không chứng minh nhân quả.',
        'Chọn lại tham số sau khi xem test làm thiên lệch; không tự chọn tham số thắng nhất.']}

def sensitivity(f,b=None,horizon=10):
    rows=[]
    for c in [.1,1.,10.]:
        r=walk_forward(f,b,horizon,c);rows.append({'C':c,'oos_samples':r['oos_samples'],'brier':r.get('oos_brier'),'mean_selected':r.get('mean_selected_net_return')})
    return {'items':rows,'warning':'Cùng tập OOS, không độc lập; không tự chọn tham số tối ưu.'}

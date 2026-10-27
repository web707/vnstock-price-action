"""Chronological fixed-rule diagnostics. Not a calibrated forecast or execution backtest."""
import math
import numpy as np
import pandas as pd
from src.data_quality import assess
from src.research import indicators,score_components


def summarize(returns):
    a=np.array(returns,dtype=float);n=len(a)
    if not n:return {'count':0,'mean_net_pct':None,'median_net_pct':None,'win_rate_pct':None,'win_interval_pct':None,'profit_factor':None,'worst_net_pct':None}
    wins=int((a>0).sum());p=wins/n;z=1.96
    denom=1+z*z/n;center=(p+z*z/(2*n))/denom
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/denom
    losses=-a[a<0].sum()
    return {'count':n,'mean_net_pct':float(a.mean()*100),'median_net_pct':float(np.median(a)*100),
            'win_rate_pct':100*p,'win_interval_pct':[max(0,center-half)*100,min(1,center+half)*100],
            'profit_factor':float(a[a>0].sum()/losses) if losses>0 else None,'worst_net_pct':float(a.min()*100)}


def evaluate(frame, horizon=10, threshold=70, min_volume=100000, fee_pct=.15, tax_pct=.1, slippage_pct=.1, as_of=None):
    if horizon not in (5,10,20):raise ValueError('Kỳ nắm giữ chỉ hỗ trợ 5, 10 hoặc 20 nến ngày.')
    if not all(math.isfinite(x) for x in (threshold,min_volume,fee_pct,tax_pct,slippage_pct)):
        raise ValueError('Tham số phải hữu hạn.')
    if not (0<=threshold<=100 and min_volume>=0 and all(0<=v<=5 for v in (fee_pct,tax_pct,slippage_pct))):
        raise ValueError('Tham số ngoài giới hạn.')
    quality=assess(frame,as_of)
    if quality['status']=='INVALID':raise ValueError('Dữ liệu không hợp lệ; không đánh giá tín hiệu.')
    f=frame.copy().sort_values('TRADE_DATE').reset_index(drop=True) if not frame.empty else frame.copy()
    if len(f)<200+horizon:
        return {'status':'INSUFFICIENT_HISTORY','message':f'Cần ít nhất {200+horizon} nến ngày đã đóng.','bars':len(f),'quality':quality}
    i=indicators(f);scores=score_components(f,i).sum(axis=1)
    # Known at decision time. No filter based on subsequent returns.
    clean_volume=(f.VOLUME>0).rolling(20).sum().eq(20)
    labels=f.get('QUALITY_STATUS',pd.Series('UNKNOWN',index=f.index)).fillna('UNKNOWN')
    clean_labels=labels.eq('VALID').rolling(20).sum().eq(20)
    safe_moves=f.CLOSE_PRICE.pct_change(fill_method=None).abs().le(.20).rolling(20).sum().eq(20)
    sources=f.get('SOURCE',pd.Series('UNKNOWN',index=f.index)).fillna('UNKNOWN').astype(str)
    # Reject mixed recent provider series without calling VALID source certification.
    one_source=sources.eq(sources.shift()).rolling(19).sum().eq(19)
    eligible=(i.avg_volume20>=min_volume)&clean_volume&clean_labels&safe_moves&one_source
    fee=fee_pct/100;tax=tax_pct/100;slip=slippage_pct/100
    observations=[];rejected={'signal_quality_or_liquidity':0,'unavailable_execution_volume':0};scheduled=0
    # Fixed non-overlapping entry/exit windows. Signal on close t, entry open t+1.
    for t in range(199,len(f)-horizon,horizon):
        scheduled+=1
        if not eligible.iloc[t]:rejected['signal_quality_or_liquidity']+=1;continue
        entry=t+1;end=t+horizon
        # A missing execution is recorded separately, never filled at a fictitious price.
        if f.VOLUME.iloc[entry]<=0 or f.VOLUME.iloc[end]<=0:
            rejected['unavailable_execution_volume']+=1;continue
        buy=float(f.OPEN_PRICE.iloc[entry]);sell=float(f.CLOSE_PRICE.iloc[end])
        net=(sell*(1-slip)*(1-fee-tax))/(buy*(1+slip)*(1+fee))-1
        observations.append({'signal_date':str(f.TRADE_DATE.iloc[t])[:10],
            'entry_date':str(f.TRADE_DATE.iloc[entry])[:10],'exit_date':str(f.TRADE_DATE.iloc[end])[:10],
            'entry_open':buy,'exit_close':sell,'score':int(scores.iloc[t]),'selected':bool(scores.iloc[t]>=threshold),
            'gross_return_pct':(sell/buy-1)*100,'net_return_pct':net*100,'grid_index':scheduled-1})
    selected=[o['net_return_pct']/100 for o in observations if o['selected']]
    baseline=[o['net_return_pct']/100 for o in observations]
    a=summarize(selected);b=summarize(baseline)
    difference=(a['mean_net_pct']-b['mean_net_pct']) if selected else None
    folds=[]
    for n,indices in enumerate(np.array_split(np.arange(scheduled),4),1):
        if not len(indices):continue
        rows=[o for o in observations if int(indices[0])<=o['grid_index']<=int(indices[-1])]
        chosen=[o['net_return_pct']/100 for o in rows if o['selected']]
        folds.append({'period':n,'first_signal':str(f.TRADE_DATE.iloc[199+int(indices[0])*horizon])[:10],
            'last_signal':str(f.TRADE_DATE.iloc[199+int(indices[-1])*horizon])[:10],
            'signal':summarize(chosen),'baseline':summarize([o['net_return_pct']/100 for o in rows])})
    status='TOO_FEW_SAMPLES' if len(selected)<20 else ('NO_OBSERVED_ADVANTAGE' if difference<=0 else 'POSITIVE_DESCRIPTIVE_DIFFERENCE')
    return {'status':status,'bars':len(f),'as_of':str(f.TRADE_DATE.iloc[-1])[:10],
        'parameters':{'horizon':horizon,'threshold':threshold,'min_volume':min_volume,'fee_pct':fee_pct,'tax_pct':tax_pct,'slippage_pct':slippage_pct},
        'signal':a,'baseline':b,'difference_pp':difference,'scheduled_windows':scheduled,'excluded':rejected,
        'selection_rate_pct':100*len(selected)/len(baseline) if baseline else None,
        'periods':folds,'observations':observations,'quality':quality,
        'method':'Quy tắc cố định trên lịch sử, tối đa 4 giai đoạn liên tiếp; không huấn luyện/tối ưu tham số.',
        'limitations':[
            'Chưa phải kiểm định ngoài mẫu độc lập: xem kết quả rồi đổi tham số có thể gây overfitting.',
            'So sánh lợi suất bình quân từng cửa sổ cùng kỳ; nhóm điểm cao là tập con của baseline. Không phải lợi nhuận danh mục hay buy-and-hold.',
            'Kỳ tính bằng số bản ghi giá; thiếu phiên có thể kéo dài thời gian thực tế. Không xác nhận lịch nghỉ lễ.',
            'Giả định mua open phiên kế tiếp, bán close sau kỳ giữ. Chưa mô phỏng T+2, giới hạn giá, lô, khớp lệnh hay stop-loss; phí/thuế là giả định.',
            'Không chồng lấn cửa sổ nhưng các quan sát vẫn có thể phụ thuộc. Khoảng Wilson 95% chỉ mô tả tỷ lệ thắng lịch sử, không phải xác suất tương lai.',
            'Giá, điều chỉnh quyền và danh mục niêm yết chưa được đối chiếu độc lập. Không xác nhận xử lý chia tách/cổ tức; có thể có thiên lệch sống sót.',
            'Cửa sổ không có volume tại giá vào/ra được báo riêng và loại khỏi thống kê; việc loại này có thể gây thiên lệch.',
        ]}

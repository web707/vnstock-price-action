"""Causal daily research indicators. Scores are rules, not calibrated probabilities."""
import math
import numpy as np
import pandas as pd
from src.data_quality import assess


def wilder(series, period=14):
    """Arithmetic seed followed by Wilder recursion; no future observations."""
    values=series.to_numpy(dtype=float)
    out=np.full(len(values),np.nan)
    if len(values)>=period:
        out[period-1]=values[:period].mean()
        for i in range(period,len(values)):
            out[i]=(out[i-1]*(period-1)+values[i])/period
    return pd.Series(out,index=series.index)


def indicators(df):
    c=df.CLOSE_PRICE.astype(float);h=df.HIGH_PRICE.astype(float);l=df.LOW_PRICE.astype(float)
    result=pd.DataFrame(index=df.index)
    for n in (20,50,200):result[f'ma{n}']=c.rolling(n,min_periods=n).mean()
    delta=c.diff().iloc[1:]
    gain=wilder(delta.clip(lower=0));loss=wilder(-delta.clip(upper=0))
    rsi=100-100/(1+gain/loss.replace(0,np.nan))
    rsi=rsi.mask((loss==0)&(gain>0),100).mask((gain==0)&(loss>0),0).mask((gain==0)&(loss==0),50)
    result['rsi14']=rsi
    result['macd']=c.ewm(span=12,adjust=False,min_periods=12).mean()-c.ewm(span=26,adjust=False,min_periods=26).mean()
    result['macd_signal']=result.macd.ewm(span=9,adjust=False,min_periods=9).mean()
    result['macd_hist']=result.macd-result.macd_signal
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    result['atr14']=wilder(tr)
    result['volume_ratio']=df.VOLUME/df.VOLUME.shift(1).rolling(20).mean().replace(0,np.nan)
    result['avg_volume20']=df.VOLUME.rolling(20).mean()
    result['turnover20']=(c*df.VOLUME).rolling(20).mean()
    result['prior_high20']=h.shift(1).rolling(20).max()
    result['prior_low20']=l.shift(1).rolling(20).min()
    return result



def score_components(df, indicators_frame=None):
    """One causal rule implementation shared by live research and historical evaluation."""
    i=indicators(df) if indicators_frame is None else indicators_frame
    c=df.CLOSE_PRICE.astype(float)
    rules={
        'Giá trên MA20':(c>i.ma20,20),
        'MA20 trên MA50':(i.ma20>i.ma50,20),
        'Giá trên MA200':(c>i.ma200,15),
        'RSI trong khoảng 50–70':(i.rsi14.between(50,70),15),
        'MACD histogram dương':(i.macd_hist>0,15),
        'Vượt đỉnh 20 phiên trước với volume ít nhất 1,5 lần':((c>i.prior_high20)&(i.volume_ratio>=1.5),15),
    }
    return pd.DataFrame({label:condition.fillna(False).astype(int)*weight for label,(condition,weight) in rules.items()},index=df.index)


def analyze(df, as_of=None):
    if df.empty:return {'status':'NO_DATA','score':None,'reasons':['Không có dữ liệu giá.']}
    quality=assess(df,as_of)
    if quality['status']=='INVALID':
        return {'status':'INVALID','score':None,'quality':quality,'reasons':quality['reasons']}
    df=df.copy().sort_values('TRADE_DATE').reset_index(drop=True)
    if len(df)<60:
        return {'status':'INSUFFICIENT_DATA','score':None,'bars':len(df),'quality':quality,'reasons':['Cần ít nhất 60 nến ngày đã đóng.']}
    indicator_frame=indicators(df)
    row=indicator_frame.iloc[-1]
    values={k:float(v) if pd.notna(v) and math.isfinite(v) else None for k,v in row.items()}
    close=float(df.CLOSE_PRICE.iloc[-1]);score=0;reasons=[]
    components=score_components(df, indicators_frame=indicator_frame).iloc[-1]
    for label,points in components.items():
        reasons.append({'rule':label,'met':bool(points),'points':int(points)})
        score+=int(points)
    recent=assess(df.tail(120),as_of)
    caution=[]
    if len(df)<200:caution.append('Chưa đủ 200 phiên: tiêu chí MA200 chưa được đánh giá, điểm không được chuẩn hoá lại.')
    if recent['status']=='REVIEW':caution+=recent['reasons']
    caution.append('Nguồn và cơ sở điều chỉnh giá chưa xác minh; chỉ dùng để nghiên cứu.')
    if row.rsi14>70:caution.append('RSI trên 70: động lượng cao nhưng có nguy cơ mua đuổi.')
    if row.atr14/close>0.05:caution.append('ATR vượt 5% giá: biên độ dao động lớn.')
    trend='UPTREND' if close>row.ma20>row.ma50 else ('DOWNTREND' if close<row.ma20<row.ma50 else 'MIXED')
    return {'status':'REVIEW' if recent['status']=='REVIEW' else 'UNVERIFIED','score':score,
            'score_definition':'Đồng thuận quy tắc 0–100; không phải xác suất sinh lời.',
            'available_score_max':100 if len(df)>=200 else 85,
            'trend':trend,'bars':len(df),'data_as_of':str(df.TRADE_DATE.iloc[-1])[:10],
            'close':close,'price_history':[{'date':str(r.TRADE_DATE)[:10],'close':float(r.CLOSE_PRICE)} for r in df.tail(60).itertuples()],
            'indicators':values,'quality':quality,'recent_quality':recent,
            'reasons':reasons,'warnings':caution,'price_unit':'unverified',
            'scenarios':{'bull':f'Đóng cửa vượt {row.prior_high20:.4f} cùng volume xác nhận; cần theo dõi phiên kế tiếp.',
                         'bear':f'Đóng cửa dưới đáy 20 phiên trước {row.prior_low20:.4f}: cấu trúc ngắn hạn suy yếu.'}}


def size_position(capital, entry, stop, target, risk_pct=1, max_position_pct=20, fee_pct=0.15, sell_tax_pct=0.1, slippage_pct=0.1, lot=100):
    args=[capital,entry,stop,target,risk_pct,max_position_pct,fee_pct,sell_tax_pct,slippage_pct]
    if not all(math.isfinite(x) for x in args):raise ValueError('Giá trị phải hữu hạn.')
    if not (capital>0 and 0<stop<entry<target):raise ValueError('Lệnh mua cần 0 < stop < entry < target và vốn > 0.')
    if not (0<risk_pct<=5 and 0<max_position_pct<=100 and all(0<=x<=5 for x in [fee_pct,sell_tax_pct,slippage_pct]) and lot in (1,100)):
        raise ValueError('Thông số rủi ro, phí hoặc lô không hợp lệ.')
    slip=slippage_pct/100;fee=fee_pct/100;tax=sell_tax_pct/100
    buy=entry*(1+slip)*(1+fee)
    sell_stop=stop*(1-slip)*(1-fee-tax)
    sell_target=target*(1-slip)*(1-fee-tax)
    unit_risk=buy-sell_stop;budget=capital*risk_pct/100;cap=capital*max_position_pct/100
    shares=int(min(budget/unit_risk,cap/buy)//lot)*lot
    return {'shares':shares,'cost':shares*buy,'planned_loss':shares*unit_risk,'risk_budget':budget,
            'position_cap':cap,'net_rr':(sell_target-buy)/unit_risk,
            'planned_profit':shares*(sell_target-buy),'currency':'VND',
            'warning':'Nhập giá đồng/cổ phiếu. Phí/thuế/trượt giá là giả định do bạn chọn. Gap, giá sàn hoặc thiếu thanh khoản có thể làm lỗ vượt dự kiến; stop không được bảo đảm khớp.'}
